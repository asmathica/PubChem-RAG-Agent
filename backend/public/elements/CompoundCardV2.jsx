import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { FlaskConical, Weight, Droplets, Layers, ExternalLink, Atom, Scale, Hash, Gauge, Sparkles } from "lucide-react"

// Render a formula like "C9H8O4" with proper subscripts for digits.
function formatFormula(formula) {
  if (!formula) return "—"
  return formula.split("").map((ch, index) => {
    if (/\d/.test(ch)) return <sub key={index}>{ch}</sub>
    return <span key={index}>{ch}</span>
  })
}

// Compact tile: icon on the left, label above, value below.
function Tile({ icon, label, value, unit, mono }) {
  if (value === undefined || value === null || value === "") return null
  return (
    <div
      className="flex items-center gap-3 rounded-xl border px-3 py-2"
      style={{
        borderColor: "hsl(var(--border))",
        background: "color-mix(in srgb, hsl(var(--secondary)) 60%, transparent)",
      }}
    >
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
        style={{ background: "color-mix(in srgb, hsl(var(--primary)) 14%, transparent)" }}
      >
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <div
          className="text-[10px] font-medium uppercase tracking-[0.18em]"
          style={{ color: "hsl(var(--muted-foreground))" }}
        >
          {label}
        </div>
        <div
          className={`truncate text-sm font-semibold ${mono ? "font-mono" : ""}`}
          style={{ color: "hsl(var(--foreground))" }}
        >
          {value}
          {unit ? (
            <span className="ml-1 text-xs font-normal" style={{ color: "hsl(var(--muted-foreground))" }}>
              {unit}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  )
}

// Big "hero" tile for the two most important properties (formula + weight).
function HeroTile({ icon, label, value, unit }) {
  return (
    <div
      className="rounded-xl border px-4 py-3"
      style={{
        borderColor: "hsl(var(--border))",
        background: "color-mix(in srgb, hsl(var(--primary)) 8%, transparent)",
      }}
    >
      <div className="mb-1 flex items-center gap-2">
        <div
          className="flex h-7 w-7 items-center justify-center rounded-md"
          style={{ background: "color-mix(in srgb, hsl(var(--primary)) 18%, transparent)" }}
        >
          {icon}
        </div>
        <div
          className="text-[10px] font-semibold uppercase tracking-[0.2em]"
          style={{ color: "hsl(var(--muted-foreground))" }}
        >
          {label}
        </div>
      </div>
      <div className="text-lg font-bold leading-tight" style={{ color: "hsl(var(--foreground))" }}>
        {value}
        {unit ? (
          <span className="ml-1 text-sm font-normal" style={{ color: "hsl(var(--muted-foreground))" }}>
            {unit}
          </span>
        ) : null}
      </div>
    </div>
  )
}

export default function CompoundCard() {
  const name = props.name || "Unknown compound"
  const iupac = props.iupac_name || null
  const imageUrl = props.image_url || null
  const pubchemUrl = props.pubchem_url || null
  const whyItMatches = props.why_it_matches || null
  const synonyms = Array.isArray(props.synonyms) ? props.synonyms : []
  const formula = props.molecular_formula || null
  const weight = props.molecular_weight != null ? Number(props.molecular_weight).toFixed(2) : null

  const iconStyle = { color: "hsl(var(--primary))" }

  return (
    <Card
      className="w-full max-w-3xl overflow-hidden border"
      style={{
        background: "hsl(var(--card))",
        color: "hsl(var(--card-foreground))",
        borderColor: "hsl(var(--border))",
        boxShadow: "none",
      }}
    >
      {/* HEADER: name + IUPAC + CID badge + link */}
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <CardTitle className="truncate text-xl font-semibold">{name}</CardTitle>
            {iupac ? (
              <div className="mt-1 text-sm italic" style={{ color: "hsl(var(--muted-foreground))" }}>
                {iupac}
              </div>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {props.cid ? (
              <Badge
                variant="outline"
                className="border-0 font-mono"
                style={{
                  background: "color-mix(in srgb, hsl(var(--primary)) 14%, transparent)",
                  color: "hsl(var(--primary))",
                }}
              >
                CID {props.cid}
              </Badge>
            ) : null}
            {pubchemUrl ? (
              <a
                href={pubchemUrl}
                target="_blank"
                rel="noreferrer"
                className="flex h-8 w-8 items-center justify-center rounded-lg border transition-colors"
                style={{ borderColor: "hsl(var(--border))", color: "hsl(var(--primary))" }}
              >
                <ExternalLink className="h-4 w-4" />
              </a>
            ) : null}
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4 pt-0">
        {/* HERO: structure thumbnail + the two most-important properties */}
        <div className="grid gap-4" style={{ gridTemplateColumns: imageUrl ? "150px 1fr" : "1fr" }}>
          {imageUrl ? (
            <div
              className="flex h-[140px] w-[150px] items-center justify-center rounded-2xl border bg-white p-3"
              style={{ borderColor: "hsl(var(--border))" }}
            >
              <img
                src={imageUrl}
                alt={`${name} structure`}
                className="max-h-full max-w-full object-contain"
              />
            </div>
          ) : null}

          <div className="grid gap-3" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <HeroTile
              icon={<FlaskConical className="h-4 w-4" style={iconStyle} />}
              label="Формула"
              value={<span className="font-mono">{formatFormula(formula)}</span>}
            />
            <HeroTile
              icon={<Weight className="h-4 w-4" style={iconStyle} />}
              label="Мол. масса"
              value={weight ?? "—"}
              unit={weight ? "г/моль" : null}
            />
          </div>
        </div>

        {/* PROPERTIES GRID: always 2 columns, hides empty tiles */}
        <Separator />
        <div className="grid gap-3" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Tile
            icon={<Droplets className="h-4 w-4" style={iconStyle} />}
            label="XLogP"
            value={props.xlogp}
          />
          <Tile
            icon={<Layers className="h-4 w-4" style={iconStyle} />}
            label="Complexity"
            value={props.complexity}
          />
          <Tile
            icon={<Atom className="h-4 w-4" style={iconStyle} />}
            label="H-доноры"
            value={props.hbond_donor_count}
          />
          <Tile
            icon={<Atom className="h-4 w-4" style={iconStyle} />}
            label="H-акцепторы"
            value={props.hbond_acceptor_count}
          />
          <Tile
            icon={<Gauge className="h-4 w-4" style={iconStyle} />}
            label="TPSA"
            value={props.tpsa}
            unit="Å²"
          />
          <Tile
            icon={<Scale className="h-4 w-4" style={iconStyle} />}
            label="Exact mass"
            value={props.exact_mass != null ? Number(props.exact_mass).toFixed(4) : null}
          />
          <Tile
            icon={<Hash className="h-4 w-4" style={iconStyle} />}
            label="Заряд"
            value={props.charge != null ? (props.charge === 0 ? "0 (нейтральный)" : props.charge) : null}
          />
          {props.inchi_key ? (
            <Tile
              icon={<Sparkles className="h-4 w-4" style={iconStyle} />}
              label="InChI Key"
              value={props.inchi_key}
              mono
            />
          ) : null}
        </div>

        {/* CANONICAL SMILES — full width row, mono, with tooltip */}
        {props.canonical_smiles ? (
          <>
            <Separator />
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div
                    className="cursor-default truncate rounded-xl border px-3 py-2 font-mono text-xs"
                    style={{
                      borderColor: "hsl(var(--border))",
                      background: "color-mix(in srgb, hsl(var(--secondary)) 60%, transparent)",
                      color: "hsl(var(--muted-foreground))",
                    }}
                  >
                    <span
                      className="mr-2 text-[10px] uppercase tracking-[0.18em]"
                      style={{ color: "hsl(var(--primary))" }}
                    >
                      SMILES
                    </span>
                    {props.canonical_smiles}
                  </div>
                </TooltipTrigger>
                <TooltipContent side="top">Canonical SMILES</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </>
        ) : null}

        {/* WHY IT MATCHES — full width, primary-tinted card */}
        {whyItMatches ? (
          <>
            <Separator />
            <div
              className="rounded-2xl border px-4 py-3 text-sm leading-relaxed"
              style={{
                borderColor: "hsl(var(--border))",
                background: "color-mix(in srgb, hsl(var(--primary)) 10%, transparent)",
              }}
            >
              <div
                className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em]"
                style={{ color: "hsl(var(--primary))" }}
              >
                Почему результат подходит
              </div>
              <div style={{ color: "hsl(var(--foreground))" }}>{whyItMatches}</div>
            </div>
          </>
        ) : null}

        {/* SYNONYMS — small chips */}
        {synonyms.length > 0 ? (
          <>
            <Separator />
            <div className="flex flex-wrap gap-2">
              {synonyms.slice(0, 6).map((synonym, index) => (
                <Badge
                  key={index}
                  variant="outline"
                  className="border-0 text-xs"
                  style={{
                    background: "color-mix(in srgb, hsl(var(--muted)) 92%, transparent)",
                    color: "hsl(var(--muted-foreground))",
                  }}
                >
                  {synonym}
                </Badge>
              ))}
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}
