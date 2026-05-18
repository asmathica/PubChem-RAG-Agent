from __future__ import annotations

from typing import cast
import json
import uuid

import chainlit as cl

from app.agent.meta import is_capability_question
from app.container import AppContainer, build_container
from app.errors.models import AppError
from app.presenters.compound_card import (
    build_candidates_markdown,
    build_compound_card_props,
    build_structure_image_url,
    build_tool_trace_markdown,
    extract_primary_synonyms,
    select_primary_compound,
)
from app.schemas.agent import AgentRequest, AgentResponseEnvelope


def _get_or_create_container() -> AppContainer:
    container = cl.user_session.get("container")
    if container is None:
        container = build_container()
        cl.user_session.set("container", container)
    return cast(AppContainer, container)


def _get_session_id() -> str:
    session_id = cl.user_session.get("pubchem_session_id")
    if session_id is None:
        session_id = uuid.uuid4().hex
        cl.user_session.set("pubchem_session_id", session_id)
    return cast(str, session_id)


def _humanize_runtime_error(exc: BaseException) -> str:
    """Map noisy upstream / framework exceptions into a single short Russian
    sentence the chat user can act on, instead of the generic
    'Не удалось завершить запрос из-за внутренней ошибки приложения.'
    """
    text = repr(exc)
    if "RESOURCE_EXHAUSTED" in text or "429" in text:
        return "Лимит запросов к LLM временно исчерпан — подождите минуту и повторите."
    if "GraphRecursionError" in text or "Recursion limit" in text:
        return "Агент сделал слишком много шагов. Сформулируйте запрос более конкретно или повторите."
    if "ServerError" in text or "500 INTERNAL" in text or "503" in text or "INTERNAL" in text:
        return "Языковая модель временно недоступна (5xx у провайдера). Попробуйте ещё раз через несколько секунд."
    if "TimeoutError" in text or "Timeout" in text:
        return "Запрос занял слишком много времени. Сократите формулировку или попробуйте позже."
    return "Не удалось завершить запрос — попробуйте ещё раз. Если проблема повторится, проверьте логи бэкенда."


def _build_details_markdown(response: AgentResponseEnvelope) -> str:
    """Markdown for the right side panel.

    The MCP search tools only return cid / title / formula / molecular_weight
    today, so the rich-field block (IUPAC, SMILES, XLogP…) is almost always
    empty. Without a fallback the panel ends up as a lonely "### Подробности"
    header. Always emit the basics that ARE available, plus the trace and a
    direct PubChem link, so the user has something useful to look at.
    """
    normalized = response.normalized
    if normalized is None:
        return "Подробные сведения недоступны."

    primary = select_primary_compound(response)
    if primary is None:
        return build_tool_trace_markdown(response)

    lines: list[str] = [f"### {primary.title or f'CID {primary.cid}'}"]

    basics: list[str] = []
    basics.append(f"- **PubChem CID:** {primary.cid}")
    if primary.molecular_formula:
        basics.append(f"- **Молекулярная формула:** `{primary.molecular_formula}`")
    if primary.molecular_weight is not None:
        basics.append(f"- **Молекулярная масса:** {primary.molecular_weight:.2f} г/моль")
    if primary.iupac_name:
        basics.append(f"- **IUPAC:** {primary.iupac_name}")
    if primary.canonical_smiles:
        basics.append(f"- **Canonical SMILES:** `{primary.canonical_smiles}`")
    if primary.exact_mass is not None:
        basics.append(f"- **Exact mass:** {primary.exact_mass:.4f}")
    if primary.xlogp is not None:
        basics.append(f"- **XLogP:** {primary.xlogp}")
    if primary.tpsa is not None:
        basics.append(f"- **TPSA:** {primary.tpsa}")
    if primary.complexity is not None:
        basics.append(f"- **Complexity:** {primary.complexity}")
    if primary.hbond_donor_count is not None or primary.hbond_acceptor_count is not None:
        donor = primary.hbond_donor_count if primary.hbond_donor_count is not None else "—"
        acceptor = primary.hbond_acceptor_count if primary.hbond_acceptor_count is not None else "—"
        basics.append(f"- **H-bond донор/акцептор:** {donor} / {acceptor}")
    lines.extend(basics)

    lines.append("")
    lines.append(f"[Открыть на PubChem ↗](https://pubchem.ncbi.nlm.nih.gov/compound/{primary.cid})")

    if primary.description:
        lines.append("")
        lines.append("#### Описание")
        lines.append(primary.description)

    if normalized.tool_trace:
        lines.append("")
        lines.append(build_tool_trace_markdown(response))

    return "\n".join(lines)


@cl.set_starters
async def set_starters(
    current_user: cl.User | None = None,  # noqa: ARG001
    language: str = "ru-RU",
) -> list[cl.Starter]:
    is_russian = language.lower().startswith("ru")
    if is_russian:
        return [
            cl.Starter(
                label="Антибиотик по признакам",
                message="антибиотик с бензольным кольцом, молекулярная масса около 350",
            ),
            cl.Starter(
                label="Похожее на aspirin",
                message="соединение похоже на aspirin",
            ),
            cl.Starter(
                label="Молекула по описанию",
                message="найди молекулу по описанию и верни свойства",
            ),
            cl.Starter(
                label="Какие у тебя инструменты?",
                message="Какие инструменты у тебя есть?",
            ),
        ]

    return [
        cl.Starter(
            label="Antibiotic by constraints",
            message="antibiotic with a benzene ring and molecular weight around 350",
        ),
        cl.Starter(
            label="Similar to aspirin",
            message="find a compound similar to aspirin",
        ),
        cl.Starter(
            label="Find by description",
            message="find a molecule from its description and return key properties",
        ),
        cl.Starter(
            label="What tools do you have?",
            message="What tools do you have?",
        ),
    ]


@cl.on_chat_start
async def on_chat_start() -> None:
    container = _get_or_create_container()
    _get_session_id()
    cl.user_session.set("llm_provider", container.settings.llm_default_provider)


@cl.on_chat_end
async def on_chat_end() -> None:
    container = cl.user_session.get("container")
    if container is not None:
        await cast(AppContainer, container).close()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    container = _get_or_create_container()
    session_id = _get_session_id()
    provider = cast(str, cl.user_session.get("llm_provider") or container.settings.llm_default_provider)
    trace_id = uuid.uuid4().hex
    capability_mode = is_capability_question(message.content)

    try:
        if capability_mode:
            response = await container.agent_stream_service.execute(
                AgentRequest(
                    text=message.content,
                    provider=provider,
                    include_raw=True,
                ),
                trace_id=trace_id,
                metadata_overrides={
                    "surface": "chainlit",
                    "chainlit_session_id": session_id,
                    "langfuse_session_id": session_id,
                    "langfuse_user_id": session_id,
                    "langfuse_tags": ["pubchem-agent", provider, "chainlit"],
                    "agent_provider": provider,
                },
            )
        else:
            async with cl.Step(name="Поиск в PubChem") as step:
                step.output = "Ищу кандидатов в PubChem и собираю ключевые свойства..."
                response = await container.agent_stream_service.execute(
                    AgentRequest(
                        text=message.content,
                        provider=provider,
                        include_raw=True,
                    ),
                    trace_id=trace_id,
                    metadata_overrides={
                        "surface": "chainlit",
                        "chainlit_session_id": session_id,
                        "langfuse_session_id": session_id,
                        "langfuse_user_id": session_id,
                        "langfuse_tags": ["pubchem-agent", provider, "chainlit"],
                        "agent_provider": provider,
                    },
                )
                step.output = "Поиск завершён."
    except AppError as error:
        await cl.Message(content=error.message, author="PubChem Agent").send()
        return
    except Exception as exc:
        message = _humanize_runtime_error(exc)
        await cl.Message(content=message, author="PubChem Agent").send()
        return

    normalized = response.normalized
    if normalized is None:
        await cl.Message(content="Не удалось получить итоговый ответ от агента.", author="PubChem Agent").send()
        return

    parsed_query_payload = normalized.parsed_query.model_dump(mode="json", exclude_none=True)
    async with cl.Step(name="Интерпретация запроса", show_input="json") as step:
        step.input = {"query": message.content}
        step.output = json.dumps(parsed_query_payload, ensure_ascii=False, indent=2)

    primary = select_primary_compound(response)
    inline_elements: list[cl.Element] = []
    sidebar_elements: list[cl.Element] = []
    if primary is not None:
        synonyms = extract_primary_synonyms(response, primary.cid)
        inline_elements.append(
            cl.CustomElement(
                # Renamed to V2 so the browser cannot serve the cached old
                # JSX bundle for /public/elements/CompoundCard.jsx — Chainlit
                # 2.11 does not version-hash custom-element URLs, so the
                # only reliable way to bust a stuck client is a new filename.
                name="CompoundCardV2",
                props=build_compound_card_props(
                    primary,
                    explanation=normalized.explanation,
                    synonyms=synonyms,
                ),
                display="inline",
            )
        )
        sidebar_elements.append(
            cl.Image(
                name=f"CID {primary.cid} structure",
                url=build_structure_image_url(primary.cid),
                display="side",
            )
        )
        sidebar_elements.append(
            cl.Text(
                # Renders as the section heading in the side panel — keep
                # it user-facing Russian instead of the internal "properties".
                name="Свойства вещества",
                content=_build_details_markdown(response),
                display="side",
            )
        )

    if normalized.tool_trace:
        async with cl.Step(name="Использованные инструменты", type="tool") as step:
            step.output = build_tool_trace_markdown(response)

    if len(normalized.matches) > 1:
        sidebar_elements.append(
            cl.Text(
                name="candidates",
                content="### Другие кандидаты\n" + build_candidates_markdown(normalized.matches[1:]),
                display="side",
            )
        )

    explanation_block = ""
    if normalized.explanation:
        explanation_block = "\n\nПочему результат подходит:\n" + "\n".join(
            f"- {item}" for item in normalized.explanation[:4]
        )

    clarification_block = ""
    if normalized.needs_clarification and normalized.clarification_question:
        clarification_block = f"\n\nУточнение:\n{normalized.clarification_question}"

    async with cl.Step(name="Отбор результата") as step:
        step.output = "\n".join(normalized.explanation[:4]) or (
            normalized.clarification_question or "Агент завершил поиск без дополнительного пояснения."
        )

    # Visibility into what the UI is being told to render — these go to
    # uvicorn/chainlit stdout so an operator can see exactly which custom
    # elements and sidebar items left the backend on a given turn.
    print(
        f"!!! RENDER inline={[el.__class__.__name__ + ':' + (getattr(el, 'name', '?') or '?') for el in inline_elements]} "
        f"sidebar={[el.__class__.__name__ + ':' + (getattr(el, 'name', '?') or '?') for el in sidebar_elements]} "
        f"primary_cid={primary.cid if primary else None}"
    )

    await cl.Message(
        content=f"{normalized.final_answer}{explanation_block}{clarification_block}",
        elements=inline_elements,
        author="PubChem Agent",
    ).send()

    # Push extras to the explicit element sidebar. The elements also keep
    # display="side" so Chainlit's legacy side-view effect does not clear the
    # explicit sidebar while it processes the emitted element events.
    if sidebar_elements:
        await cl.ElementSidebar.set_title(f"Подробности — {primary.title or 'вещество'}" if primary else "Подробности")
        await cl.ElementSidebar.set_elements(sidebar_elements, key=trace_id)
        print(f"!!! SIDEBAR sent {len(sidebar_elements)} elements + title='Подробности — {primary.title if primary else 'вещество'}'")
