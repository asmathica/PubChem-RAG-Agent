"""
Pydantic schemas for PubChem tool input validation.

These schemas define the structure and validation rules for all
PubChem search tools used by the chemistry agent.
"""

from pydantic import BaseModel, Field, field_validator


def clean_string(value: str) -> str:
    return value.strip()


def clean_query(title:str, value: str) -> str:
    cleaned = clean_string(value)

    if not cleaned:
         
        raise ValueError(f"{title} must not be blank")
        
    return cleaned
   
class SearchByNameInput(BaseModel):
    """
    This schema validates user input when searching for compounds
    using their common name, IUPAC name, or trade name.
    
    Attributes:
        name: The compound name or search keyword 
        limit: Maximum number of candidate compounds to return (1-10)
      
    Validation rules:
        - name must be 1-160 characters
        - name cannot be empty or whitespace only

    """
    name: str = Field(min_length=1, max_length=160, description="Compound name or search keyword from the user.")
    limit: int = Field(default=5, ge=1, le=10, description="Maximum number of candidate compounds to return.")

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: str) -> str:
        """
        Validate and clean the compound name input.
               
        """

        return clean_query("Name", value)


class SearchBySMILESInput(BaseModel):
    """ 
    This schema validates SMILES (Simplified Molecular Input Line Entry System)
    strings used for structure-based compound search.
    
    Attributes:
        smiles: SMILES string
        limit: Maximum number of candidate compounds to return (1-10)
    
    Validation rules:
        - smiles must be 1-512 characters
        - smiles cannot be empty or whitespace only
    """
    smiles: str = Field(min_length=1, max_length=512, description="SMILES string to resolve in PubChem.")
    limit: int = Field(default=5, ge=1, le=10, description="Maximum number of candidate compounds to return.")

    @field_validator("smiles", mode="before")
    @classmethod
    def strip_smiles(cls, value: str) -> str:
        """
        Validate and clean the SMILES string input.

        """
        return clean_query("SMILES", value)


class SearchByFormulaInput(BaseModel):
    """
    This schema validates molecular formula strings (Hill notation)
    for compound search based on elemental composition.
    
    Attributes:
        formula: Molecular formula in Hill notation (e.g., "C9H8O4", "CH3COOH")
        limit: Maximum number of candidate compounds to return (1-10)
    
    Validation rules:
        - formula must be 1-64 characters
        - formula cannot be empty or whitespace only
        - limit must be between 1 and 10
    """
    
    formula: str = Field(min_length=1, max_length=64, description="Molecular formula to resolve in PubChem.")
    limit: int = Field(default=5, ge=1, le=10, description="Maximum number of candidate compounds to return.")

    @field_validator("formula", mode="before")
    @classmethod
    def strip_formula(cls, value: str) -> str:
        """
        Validate and clean the molecular formula input.

        """
        return clean_query("Formula", value)


class SearchByInChIKeyArgs(BaseModel):
    """
    This schema validates InChIKey strings for compound search.
    
    InChIKey is a 27-character hashed version of the InChI identifier.
    
    Attributes:
        inchikey: InChIKey string 
        limit: Maximum number of candidate compounds to return (1-10)
    
    Validation rules:
        - inchikey must be 1-64 characters
    """
    inchikey: str = Field(min_length=1, max_length=64, description="InChIKey string to resolve in PubChem.")
    limit: int = Field(default=5, ge=1, le=10, description="Maximum number of candidate compounds to return.")

    @field_validator("inchikey", mode = "before")
    @classmethod
    def strip_inchikey(cls, value: str) -> str:

        return clean_query("InChIKey", value)
