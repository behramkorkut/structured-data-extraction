"""
Few-shot examples for insurance document extraction.

CCA-F Scenario 6, Task 4.2:
- Few-shot examples are the most effective technique for consistent output
- Examples demonstrate handling of varied document formats
- Examples show correct handling of ambiguous cases
- Examples reduce hallucination in extraction (handle missing data)

Each example shows a document snippet → expected extraction,
demonstrating the reasoning for ambiguous decisions.
"""


# ---------------------------------------------------------------------------
# IPID few-shot examples
# ---------------------------------------------------------------------------

IPID_FEW_SHOT_EXAMPLES = [
    {
        "description": "Standard IPID with all sections — demonstrates complete extraction",
        "input": (
            "Produit : API Santé Équilibre\n"
            "APICIL Mutuelle, mutuelle immatriculée sous le n° 302 927 553\n\n"
            "De quel type d'assurance s'agit-il ?\n"
            "Le produit d'assurance complémentaire santé API Santé Équilibre est destiné "
            "à rembourser tout ou partie des frais de santé. "
            "Le produit respecte les conditions légales des contrats responsables "
            "100 % SANTÉ et est éligible à la fiscalité Loi Madelin.\n\n"
            "Qu'est-ce qui est assuré ?\n"
            "Soins courants : consultations généralistes et spécialistes\n"
            "Hospitalisation : forfait journalier hospitalier\n"
            "Optique : verres et montures\n"
            "Dentaire : soins et prothèses\n\n"
            "Qu'est-ce qui n'est pas assuré ?\n"
            "- La chirurgie esthétique non prise en charge par la SS\n"
            "- Les indemnités journalières\n\n"
            "Y-a-t-il des exclusions ?\n"
            "La participation forfaitaire sur les consultations.\n"
            "La franchise sur les médicaments.\n"
        ),
        "expected_output": {
            "product_name": "API Santé Équilibre",
            "insurer_name": "APICIL Mutuelle",
            "insurer_registration": "302 927 553",
            "insurance_type": (
                "Le produit d'assurance complémentaire santé API Santé Équilibre "
                "est destiné à rembourser tout ou partie des frais de santé."
            ),
            "madelin_eligible": True,
            "responsible_contract": True,
            "covered_items": [
                {
                    "description": "Soins courants : consultations généralistes et spécialistes",
                    "category": "routine_care",
                },
                {
                    "description": "Hospitalisation : forfait journalier hospitalier",
                    "category": "hospitalization",
                },
                {"description": "Optique : verres et montures", "category": "optical"},
                {"description": "Dentaire : soins et prothèses", "category": "dental"},
            ],
            "not_covered_items": [
                "La chirurgie esthétique non prise en charge par la SS",
                "Les indemnités journalières",
            ],
            "exclusions": [
                {
                    "description": "La participation forfaitaire sur les consultations",
                    "exclusion_type": "regulatory",
                },
                {
                    "description": "La franchise sur les médicaments",
                    "exclusion_type": "regulatory",
                },
            ],
        },
        "reasoning": (
            "Madelin eligibility is explicitly stated ('éligible à la fiscalité Loi Madelin'). "
            "Responsible contract is stated ('contrats responsables 100% SANTÉ'). "
            "Exclusions are classified as 'regulatory' because they come from responsible "
            "contract rules (participation forfaitaire, franchise)."
        ),
    },
    {
        "description": "IPID with missing optional fields — demonstrates null handling",
        "input": (
            "Produit : APICIL Garantie Hospitalisation\n"
            "APICIL Mutuelle\n\n"
            "De quel type d'assurance s'agit-il ?\n"
            "Garantie hospitalisation individuelle.\n\n"
            "Qu'est-ce qui est assuré ?\n"
            "Hospitalisation : frais de séjour, honoraires chirurgicaux\n\n"
            "Qu'est-ce qui n'est pas assuré ?\n"
            "- Les soins ambulatoires\n\n"
            "Y-a-t-il des exclusions ?\n"
            "Les séjours en unités de long séjour.\n"
        ),
        "expected_output": {
            "product_name": "APICIL Garantie Hospitalisation",
            "insurer_name": "APICIL Mutuelle",
            "insurer_registration": None,
            "insurance_type": "Garantie hospitalisation individuelle.",
            "madelin_eligible": None,
            "responsible_contract": None,
            "covered_items": [
                {
                    "description": "Hospitalisation : frais de séjour, honoraires chirurgicaux",
                    "category": "hospitalization",
                },
            ],
            "not_covered_items": ["Les soins ambulatoires"],
            "exclusions": [
                {
                    "description": "Les séjours en unités de long séjour",
                    "exclusion_type": "absolute",
                },
            ],
            "geographic_coverage": None,
            "payment_frequency": None,
        },
        "reasoning": (
            "insurer_registration is null because no SIRENE number is mentioned. "
            "madelin_eligible is null because the document doesn't mention Loi Madelin. "
            "responsible_contract is null because no mention of 'contrat responsable'. "
            "CRITICAL: we return null, NOT a guessed value. "
            "The exclusion is 'absolute' (not regulatory) because long-stay units are "
            "a product design choice, not a regulatory constraint."
        ),
    },
]


# ---------------------------------------------------------------------------
# Guarantee Table few-shot examples
# ---------------------------------------------------------------------------

GUARANTEE_TABLE_FEW_SHOT_EXAMPLES = [
    {
        "description": "Standard reimbursement formats — percentage, fixed amount, zero copay",
        "input": (
            "SOINS COURANTS\n"
            "Analyses et examens de biologie médicale    100 % BR - SS\n"
            "Consultations généralistes                  100 % BR - SS\n\n"
            "HOSPITALISATION\n"
            "Forfait journalier hospitalier              100 % FR\n\n"
            "OPTIQUE\n"
            "Équipements 100% SANTÉ                     Zéro reste à charge\n\n"
            "PACK CONFORT JEUNES ET FAMILLES\n"
            "Ostéopathe    PC1: 30 € / séance 5 séances max    "
            "PC2: 40 € / séance 5 séances max    PC3: 50 € / séance 5 séances max\n"
        ),
        "expected_output": {
            "benefits": [
                {
                    "benefit_name": "Analyses et examens de biologie médicale",
                    "category": "routine_care",
                    "reimbursement": {
                        "raw_value": "100 % BR - SS",
                        "reimbursement_type": "percentage_br_minus_ss",
                        "percentage": 100.0,
                        "fixed_amount_euros": None,
                    },
                },
                {
                    "benefit_name": "Forfait journalier hospitalier",
                    "category": "hospitalization",
                    "reimbursement": {
                        "raw_value": "100 % FR",
                        "reimbursement_type": "real_costs",
                        "percentage": 100.0,
                        "fixed_amount_euros": None,
                    },
                },
                {
                    "benefit_name": "Équipements 100% SANTÉ",
                    "category": "optical",
                    "reimbursement": {
                        "raw_value": "Zéro reste à charge dans la limite du panier 100% Santé",
                        "reimbursement_type": "zero_copay",
                        "percentage": None,
                        "fixed_amount_euros": None,
                    },
                },
            ],
            "comfort_pack_options": [
                {
                    "benefit_name": "Ostéopathe",
                    "formula_levels": {
                        "PC1": "30 € / séance 5 séances max",
                        "PC2": "40 € / séance 5 séances max",
                        "PC3": "50 € / séance 5 séances max",
                    },
                },
            ],
        },
        "reasoning": (
            "'100 % BR - SS' = percentage_br_minus_ss with percentage=100.0. "
            "'100 % FR' = real_costs (Frais Réels), percentage set to 100.0. "
            "'Zéro reste à charge' = zero_copay, no percentage or amount. "
            "Pack Confort options: preserve exact text per formula level."
        ),
    },
    {
        "description": "Handling empty/absent reimbursement cells in table",
        "input": (
            "OPTIQUE\n"
            "Lentilles prises en charge par la SS     100 % BR - SS\n"
            "Lentilles non prises en charge par la SS  \n"
            "Chirurgie réfractive                      \n"
        ),
        "expected_output": {
            "benefits": [
                {
                    "benefit_name": "Lentilles prises en charge par la SS",
                    "category": "optical",
                    "reimbursement": {
                        "raw_value": "100 % BR - SS",
                        "reimbursement_type": "percentage_br_minus_ss",
                        "percentage": 100.0,
                    },
                    "requires_social_security": True,
                },
                {
                    "benefit_name": "Lentilles non prises en charge par la SS",
                    "category": "optical",
                    "reimbursement": {
                        "raw_value": "Non couvert à ce niveau",
                        "reimbursement_type": "other",
                        "reimbursement_type_detail": "Benefit not covered at this guarantee level",
                        "percentage": None,
                        "fixed_amount_euros": None,
                    },
                    "requires_social_security": False,
                },
            ],
        },
        "reasoning": (
            "When a reimbursement cell is EMPTY in the table, this means the benefit "
            "is NOT covered at this guarantee level. We still extract the benefit line "
            "but mark it as reimbursement_type='other' with a detail explaining it's not covered. "
            "This is different from the benefit being absent from the document entirely. "
            "CRITICAL: do NOT fabricate a reimbursement value for empty cells."
        ),
    },
]


# ---------------------------------------------------------------------------
# Few-shot prompt formatting
# ---------------------------------------------------------------------------


def format_few_shot_examples(examples: list[dict]) -> str:
    """Format few-shot examples into a prompt string.

    Each example includes:
    - Input document snippet
    - Expected output (key fields)
    - Reasoning for ambiguous decisions

    The reasoning is crucial: it teaches Claude the decision logic,
    not just the input→output mapping (CCA-F Task 4.2).

    Args:
        examples: List of few-shot example dicts.

    Returns:
        Formatted string to include in the system prompt.
    """
    parts = ["Here are examples showing how to extract data correctly:\n"]

    for i, example in enumerate(examples, 1):
        parts.append(f"--- Example {i}: {example['description']} ---")
        parts.append(f"\nINPUT:\n{example['input']}")

        # Format expected output as readable key-value pairs
        parts.append("\nEXPECTED EXTRACTION (key fields):")
        _format_output_recursive(example["expected_output"], parts, indent=2)

        parts.append(f"\nREASONING: {example['reasoning']}")
        parts.append("")  # blank line

    return "\n".join(parts)


def _format_output_recursive(obj: dict | list, parts: list[str], indent: int = 0) -> None:
    """Recursively format a nested dict/list for the prompt."""
    prefix = " " * indent
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                parts.append(f"{prefix}{key}:")
                _format_output_recursive(value, parts, indent + 2)
            else:
                parts.append(f"{prefix}{key}: {value}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                parts.append(f"{prefix}-")
                _format_output_recursive(item, parts, indent + 2)
            else:
                parts.append(f"{prefix}- {item}")


def get_ipid_few_shot_prompt() -> str:
    """Get formatted few-shot examples for IPID extraction."""
    return format_few_shot_examples(IPID_FEW_SHOT_EXAMPLES)


def get_guarantee_table_few_shot_prompt() -> str:
    """Get formatted few-shot examples for guarantee table extraction."""
    return format_few_shot_examples(GUARANTEE_TABLE_FEW_SHOT_EXAMPLES)
