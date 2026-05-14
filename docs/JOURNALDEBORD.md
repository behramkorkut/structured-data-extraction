# Scenario 6 
Perspectives : Scénario 6 — Structured Data Extraction

Tu as raison, ce scénario est parfaitement aligné avec ton profil de futur Data Engineer. Là où le Scénario 3 testait l'orchestration multi-agent, le Scénario 6 teste la fiabilité de l'extraction de données — un sujet au cœur du métier de Data Engineer.
Ce que le Scénario 6 couvre

D'après le guide officiel de l'examen, les compétences clés testées sont le JSON schema design pour tool_use, l'implémentation de boucles validation-retry, le few-shot prompting pour la cohérence de format, et la confiance au niveau des champs avec human review.
Les concepts qui changent par rapport au Scénario 3

tool_use pour garantir la structure, pas la sémantique. Dans le Scénario 3, tes sous-agents retournaient du texte libre (JSON dans une string). Dans le Scénario 6, tu utilises tool_use avec un JSON schema strict pour que Claude retourne directement un objet structuré. Le piège de l'examen : beaucoup de candidats pensent que tool_use élimine toutes les erreurs. En réalité, il garantit que tu reçois un JSON valide avec les bons types et les bons champs — mais la valeur dans chaque champ peut être fausse. Un montant de facture peut être extrait comme "total": 450.00 alors que le vrai montant est $500.00. C'est pour ça que la boucle validation-retry existe.

Les champs nullable pour prévenir l'hallucination. C'est un concept que tu n'as pas encore rencontré et qui est critique pour un Data Engineer. Quand tu définis un schema avec "tax_id": {"type": "string"} comme champ required, Claude est forcé de produire une valeur — et s'il n'en trouve pas dans le document, il en invente une. La solution : "tax_id": {"type": ["string", "null"]}. Claude peut retourner null au lieu d'halluciner. L'examen teste ce concept directement.

La boucle validation-retry. Tu extrais les données avec tool_use, tu valides (le total des lignes correspond-il au sous-total ? la date est-elle au bon format ? le numéro de TVA existe-t-il ?), et si la validation échoue, tu renvoies les erreurs spécifiques à Claude pour qu'il corrige. Pas "il y a des erreurs, réessaie" (anti-pattern), mais "le total des lignes ($450) ne correspond pas au sous-total affiché ($500), et le champ tax contient un pourcentage (10%) au lieu d'un montant en dollars." C'est exactement le pattern ETL que tu connais : extract, validate, retry/reject.

Le few-shot prompting. Pour que Claude extraie des factures de façon cohérente, tu lui montres 2-4 exemples d'extraction réussie, dont au moins un cas limite (champ manquant, format ambigu). L'examen dit que 2-4 exemples est optimal — moins de 2 n'établit pas un pattern, plus de 6 gonfle le prompt sans bénéfice proportionnel.

Les métriques stratifiées. C'est le concept anti-pattern #10 : si tu mesures la précision globale à 95%, tu peux masquer le fait que les factures sont à 70% et les reçus à 99%. Le Scénario 6 exige de tracker la précision par type de document. Pour un Data Engineer, c'est le même principe que monitorer la qualité des données par source dans un pipeline ETL.

Le Batch API. Pour le traitement en volume (audits nocturnes, scans hebdomadaires), l'examen attend que tu utilises le Batch API d'Anthropic qui offre 50% de réduction. Pour les tâches bloquantes (review de PR, extraction temps réel), tu restes en synchrone. C'est un choix d'architecture que l'examen teste.
Le lien avec ton profil Data Engineer

Le Scénario 6 est essentiellement un pipeline ETL intelligent : tu prends des documents non structurés (PDF de factures, contrats, reçus), tu en extrais des données structurées (JSON validé), tu gères les erreurs et les cas limites (champs manquants, formats incohérents), et tu monitores la qualité par catégorie. La seule différence avec un pipeline classique, c'est que l'étape "Transform" est faite par Claude au lieu d'expressions régulières ou de règles codées en dur. Ton expérience RAG avec Puls-Events (extraction d'événements depuis l'API OpenAgenda) et ton Scénario 3 (provenance, erreurs structurées) te donnent une base solide pour attaquer le Scénario 6.
Ce que tu pourrais construire

Un pipeline qui prend des factures PDF simulées, extrait les champs via tool_use avec un schema strict (nullable fields pour les champs optionnels), valide chaque extraction (totaux cohérents, dates valides, formats corrects), retry avec erreurs spécifiques si la validation échoue, et track la précision par type de document. C'est un projet portfolio parfait pour un Data Engineer qui montre qu'il sait gérer la qualité des données même quand la source est un LLM.


# Scenario 6 : Structured Data Extraction Pipeline — Plan du Projet

## Ce que dit l'exam guide

    "Vous construisez un système d'extraction de données structurées avec Claude. Le système extrait des informations à partir de documents non structurés, valide les résultats avec des schémas JSON, et maintient une haute précision. Il doit gérer les cas limites et s'intégrer avec des systèmes en aval."

## Domaines principaux : Domain 4 (Prompt Engineering & Structured Output — 20%) + Domain 5 (Context Management & Reliability — 15%)
Les concepts-clés à démontrer (tirés des Task Statements)

Domain 4 :

    tool_use avec JSON schemas pour un output structuré garanti (Task 4.3)
    tool_choice : "auto", "any", et forced selection (Task 4.3)
    Schémas avec champs required vs optional (nullable), enums avec "other" + detail string (Task 4.3)
    Few-shot prompting pour gérer les formats variés (Task 4.2)
    Critères explicites dans les prompts (Task 4.1)
    Validation-retry avec feedback d'erreur spécifique (Task 4.4)
    Message Batches API : 50% de réduction, custom_id, gestion des échecs (Task 4.5)
    Multi-pass review : instance indépendante pour vérifier les extractions (Task 4.6)

Domain 5 :

    Confidence scoring par champ, calibré avec des validation sets (Task 5.5)
    Stratiﬁed random sampling pour mesurer le taux d'erreur (Task 5.5)
    Routage vers human review pour les cas low-confidence (Task 5.5)
    Analyse de l'accuracy par type de document et par champ (Task 5.5)

## Use case concret : Extraction de Documentation assurance (pdf )

Pour rendre le projet réaliste et pertinent pour ton profil data engineer, les documents d'assurance APICIL sont un use case encore meilleur que les factures pour un data engineer. Tu as une vraie diversité de types de documents (barèmes de garanties, IPID, fiches produit, notices d'information, tarifs, exemples de remboursement) — c'est exactement ce que l'exam guide demande quand il parle de "varied document structures" et "handling edge cases gracefully."

## Architecture proposée
```
                    Documentation insurance (pdf texte variées)
                              │
                              ▼
                 ┌─────────────────────────┐
                 │   EXTRACTION PIPELINE    │
                 │                         │
                 │  1. Single Document     │
                 │     Extraction          │
                 │     (tool_use + schema) │
                 │                         │
                 │  2. Validation Layer    │
                 │     (Pydantic + semantic│
                 │      checks)           │
                 │                         │
                 │  3. Retry with Feedback │
                 │     (errors → re-prompt)│
                 │                         │
                 │  4. Confidence Scoring  │
                 │     (field-level)       │
                 │                         │
                 │  5. Quality Review      │
                 │     (independent Claude │
                 │      instance)          │
                 │                         │
                 │  6. Human Review Router │
                 │     (low confidence →   │
                 │      human queue)       │
                 └─────────┬───────────────┘
                           │
                           ▼
                 ┌─────────────────────────┐
                 │   BATCH PROCESSING      │
                 │   (Message Batches API) │
                 │   50% cost savings      │
                 │   custom_id tracking    │
                 │   failure resubmission  │
                 └─────────┬───────────────┘
                           │
                           ▼
                 ┌─────────────────────────┐
                 │   ANALYTICS & METRICS   │
                 │   Per-field accuracy     │
                 │   Per-document-type      │
                 │   Stratified sampling    │
                 └─────────────────────────┘
```

## Structure du projet
```bash 
structured-data-extraction/
├── src/
│   ├── __init__.py
│   ├── schemas.py            # JSON schemas + Pydantic models (invoice, receipt, PO)
│   ├── extraction.py         # Core extraction via tool_use
│   ├── validation.py         # Pydantic + semantic validation (totals, dates)
│   ├── retry.py              # Retry-with-error-feedback loop
│   ├── confidence.py         # Field-level confidence scoring
│   ├── review.py             # Independent Claude instance for quality review
│   ├── routing.py            # Human review routing logic
│   ├── batch.py              # Message Batches API integration
│   ├── metrics.py            # Accuracy tracking per field/document type
│   └── few_shot.py           # Few-shot examples for varied formats
├── data/
│   ├── insurance_docs/             # Sample insurance documentation (varied formats)
│   ├── labeled/              # Ground truth for validation set
│   └── results/              # Extraction outputs
├── tests/
│   ├── test_schemas.py
│   ├── test_extraction.py
│   ├── test_validation.py
│   ├── test_retry.py
│   ├── test_confidence.py
│   ├── test_review.py
│   ├── test_routing.py
│   ├── test_batch.py
│   └── test_metrics.py
├── scripts/
│   ├── extract_single.py     # Extract one document (demo)
│   ├── extract_batch.py      # Batch processing demo
│   └── run_evaluation.py     # Run against labeled set + metrics
├── .claude/
│   ├── CLAUDE.md
│   └── rules/
│       └── testing.md
├── pyproject.toml
├── Makefile
├── .env.example
└── README.md
```

## Étapes de réalisation (on fera étape par étape)

    1. Setup du projet (structure, dépendances, pyproject.toml, Makefile)
    2. Schémas & modèles (Pydantic models, JSON schemas avec nullable/enum/other)
    3. Documents d'exemple (factures dans des formats variés — email, tabulaire, narratif)
    4. Extraction core (tool_use avec forced tool selection)
    5. Validation (Pydantic + semantic checks : totaux, dates, cohérence)
    6. Retry with feedback (boucle retry avec erreurs spécifiques)
    7. Few-shot prompting (exemples pour formats variés)
    8. Confidence scoring (field-level, calibration)
    9. Quality review (instance Claude indépendante)
    10. Human review routing (low confidence → queue)
    11. Batch processing (Message Batches API)
    12. Metrics & analytics (accuracy par type/champ, stratified sampling)
    13. Tests (on écrit les tests en parallèle de chaque étape)
    14. README (vitrine recruteur, comme tes autres projets)


## Étape 1 : Initialisation du projet

1. Commande 1 — Initialise le projet UV (depuis la racine structured-data-extraction) :

cd ~/structured-data-extraction  # ou là où est ton dossier
uv init --no-readme

On fait --no-readme parce qu'on écrira notre propre README plus tard. Ça va créer pyproject.toml, .python-version, et main.py.
2. Commande 2 — Supprime le main.py généré par défaut (on n'en a pas besoin) :
3. Commande 3 — Crée la structure complète des dossiers :
4. Commande 4 — Crée tous les fichiers Python (vides pour l'instant, on les remplira étape par étape) :

5. Commande 5 — Ajoute les dépendances :
```bash 
uv add anthropic pydantic python-dotenv
uv add --dev pytest pytest-cov ruff
```
6. Commande 6 — Maintenant, remplace le contenu de pyproject.toml par la configuration complète. 

7. Commande 7 — Synchronise après la modification du pyproject.toml :
```bash 
uv sync --extra dev
```
8. Commande 8 — Crée le fichier .env.example :
9. Commande 9 — Crée le .gitignore :
10. Commande 10 — Crée le Makefile :
11. Commande 11 — Crée le .claude/CLAUDE.md :
12. Commande 12 — Crée .claude/rules/testing.md avec le path-scoping YAML :
13. Commande 13 — Vérifie que tout fonctionne :
```bash
# Vérifie la structure
tree -I '__pycache__|.venv|.git|insurance_docs' -L 3

# Vérifie que pytest fonctionne
uv run pytest tests/ -v

# Vérifie que ruff fonctionne
uv run ruff check src/ tests/
``` 

## Étape 2 : Schémas & Modèles Pydantic.

C'est le cœur du Scenario 6. 
L'exam guide insiste sur plusieurs points pour le design des schémas (Task 4.3) :

    - Champs required vs optional (nullable) — quand un document ne contient pas l'info, le modèle doit retourner null au lieu de fabriquer une valeur
    - Enums avec "other" + detail string — pour les catégories extensibles
    - Semantic validation — les totaux qui doivent correspondre, les dates cohérentes
    - Champs confidence au niveau du champ pour le routage human review (Task 5.5)

Avant de coder les schémas, j'ai besoin de comprendre la structure réelle de tes documents. Est-ce que tu peux me partager le contenu texte d'un IPID et d'un barème de garanties ? Par exemple :

    SP24FCR0103 IPID API Santé Equilibre - MAJ- 052024.pdf
    BG API Santé - Equilibre 1 avec PC MAJ 12.2025.pdf

Excellent ! Ces deux documents sont parfaits pour construire nos schémas. Je vois clairement la structure maintenant :

L'IPID c'est un document standardisé européen avec des sections fixes : type d'assurance, ce qui est assuré, ce qui n'est pas assuré, exclusions, obligations, résiliation, etc.

Le Barème de Garanties (BG) c'est un tableau structuré avec des catégories de soins (Soins courants, Hospitalisation, Optique, Dentaire, Aides auditives) et pour chaque prestation un niveau de remboursement (pourcentage BR-SS, forfait en €, etc.) + des options (Pack Confort).

C'est une richesse de données — et surtout, les deux documents ont des structures très différentes, ce qui est exactement ce que l'exam guide demande pour les few-shot examples.




### Commande — Remplis src/structured_extraction/document_loader.py :
En attendant, je te prépare déjà la partie du code qui est indépendante du contenu des documents — le document_loader.py qui va lire les PDFs et les convertir en texte.

### Commande — Ajoute pdfplumber comme dépendance :

uv add pdfplumber

### Commande — Crée maintenant les premiers tests pour le document loader. Remplis tests/test_document_loader.py :

### Commande — Lance les tests :
Maintenant, avant de coder les schémas, lance aussi les tests du document_loader pour vérifier que tout est vert :

uv run pytest tests/test_document_loader.py -v

## Schéma et Modèles Pydantic 
C'est le fichier le plus important du projet — il définit exactement ce qu'on extrait.

Commande — Remplis src/structured_extraction/schemas.py :

Maintenant, écrivons les tests pour valider ces schémas.

Commande — Remplis tests/test_schemas.py :

Commande — Lance tous les tests :

uv run pytest tests/test_schemas.py tests/test_document_loader.py -v

## Retour pédagogique sur les Étapes 1 & 2
Pourquoi ces schémas sont conçus ainsi (Task 4.3 de l'exam)

L'exam guide dit textuellement : "strict JSON schemas via tool use eliminate syntax errors but do not prevent semantic errors". C'est la distinction fondamentale à comprendre :

    Erreurs de syntaxe (éliminées par tool_use + JSON schema) : JSON mal formé, accolades manquantes, types incorrects. Quand on donne notre schéma Pydantic à Claude via tool_use, il est physiquement impossible que Claude retourne un JSON invalide. C'est de la "constrained decoding" — le modèle ne peut générer que des tokens qui respectent la grammaire du schéma.

    Erreurs sémantiques (NON éliminées par le schéma) : Claude pourrait retourner "percentage": 200.0 alors que le document dit "100% BR-SS", ou inventer un nom de garantie qui n'existe pas dans le document. C'est pour ça qu'on aura besoin de la couche validation (Étape 5) et de la couche review (Étape 9).

### Le pattern "nullable fields prevent hallucination"

C'est peut-être le concept le plus important du Scenario 6. Regarde la différence :
```bash 
# MAUVAIS — champ requis, Claude va INVENTER une valeur si absente du document
chirurgie_refractive: str  # Claude: "200€/an" (hallucination!)

# BON — champ nullable, Claude peut dire "je n'ai pas trouvé ça"
chirurgie_refractive: str | None = None  # Claude: null (honnête)
``` 

Dans nos documents APICIL, le barème "Equilibre 1" n'a PAS de montant pour la chirurgie réfractive ni pour les lentilles non-SS — le champ est vide dans le tableau. Si on rendait ces champs obligatoires (required), Claude serait forcé de produire une valeur et fabriquerait quelque chose de plausible mais faux. Avec Optional[str] = None, on lui donne une porte de sortie honnête.


### Le pattern "enum + other + detail"
```bash 
class CoverageCategory(str, Enum):
    ROUTINE_CARE = "routine_care"
    HOSPITALIZATION = "hospitalization"
    # ... catégories connues ...
    OTHER = "other"  # ← porte de sortie
``` 
Les enums classiques sont fermées : si Claude rencontre une catégorie qu'on n'a pas prévue (ex: "cure thermale"), il est forcé de la caser dans une catégorie existante, ce qui crée des erreurs silencieuses. 
Le pattern OTHER + category_detail lui permet de dire "c'est autre chose, et voici quoi". L'exam guide mentionne ce pattern explicitement comme bonne pratique.

### Pourquoi raw_value dans ReimbursementLevel
```bash
class ReimbursementLevel(BaseModel):
    raw_value: str          # "100 % BR - SS" — exactement comme dans le document
    reimbursement_type: ReimbursementType  # PERCENTAGE_BR_MINUS_SS — notre catégorie
    percentage: float | None = None         # 100.0 — valeur parsée
``` 

On garde la valeur brute du document ET sa décomposition structurée. Pourquoi ? Parce que si la validation sémantique détecte une incohérence (ex: percentage: 150 mais raw_value: "100% BR-SS"), on peut identifier si l'erreur vient du parsing ou du document source. C'est le même principe que les claim-source mappings dont parle l'exam guide pour la provenance de l'information (Task 5.6).

## Étape 3 : Extraction core avec tool_use

C'est ici que les concepts de l'exam prennent vie. On va construire le moteur d'extraction qui utilise tool_use avec tool_choice pour garantir un output structuré.

Les 3 modes de tool_choice (Task 4.3 — question d'exam fréquente) :

    - "auto" : Claude peut appeler un tool ou répondre en texte. Risque : il pourrait ignorer le tool et répondre en prose.
    - "any" : Claude doit appeler un tool, mais choisit lequel. Utile quand on a plusieurs schémas d'extraction et le type de document est inconnu.
    - {"type": "tool", "name": "extract_ipid"} : Claude doit appeler ce tool précis. C'est la forced selection — zéro ambiguïté.

### Notre stratégie : 
    - Quand on connaît le type de document (via detect_document_type), on utilise la forced selection. 
    - Quand le type est "unknown", on utilise "any" avec les deux tools disponibles et Claude choisit le bon. 
C'est exactement ce que l'exam teste.

Commande — Remplis src/structured_extraction/extraction.py :

Commande — Maintenant les tests pour l'extraction (avec API mockée — zéro coût) : tests/test_extraction.py

Commande — Lance tous les tests :

uv run pytest tests/test_schemas.py tests/test_document_loader.py tests/test_extraction.py -v

## Retour pédagogique sur l'Étape 3 : Extraction core

### Le flux complet d'une extraction

Voici ce qui se passe quand on appelle extract_document() — c'est important de visualiser le parcours de bout en bout :
```
Document texte → detect_document_type() → get_tool_choice()
                                              │
                 ┌────────────────────────────┘
                 ▼
          "ipid" détecté ?
          ┌──── OUI ──── forced: {"type": "tool", "name": "extract_ipid"}
          └──── NON ──── "any": Claude choisit le bon tool
                              │
                              ▼
                    Claude API (tool_use)
                    ┌─ system prompt: règles d'extraction
                    ├─ tools: [extract_ipid, extract_guarantee_table]
                    ├─ tool_choice: forced ou "any"
                    └─ messages: [{ "role": "user", "content": document }]
                              │
                              ▼
                    Réponse: ToolUseBlock
                    ├─ name: "extract_ipid"
                    └─ input: { "product_name": "...", ... }  ← JSON garanti valide
                              │
                              ▼
                    parse_tool_response() → (tool_name, data_dict)
                              │
                              ▼
                    Pydantic model_validate(data_dict)
                    ├─ OK → ExtractionResult(ipid=IPIDExtraction(...))
                    └─ Error → ExtractionResult(extraction_errors=[...])
```

### Pourquoi on n'utilise JAMAIS tool_choice: "auto"

C'est un point d'exam. Avec "auto", Claude peut décider de répondre en texte au lieu d'appeler un tool. Imagine la situation : tu envoies un document de 3 pages à extraire, et Claude répond "Ce document semble être un IPID pour API Santé Équilibre. Voici un résumé..." — du texte libre au lieu du JSON structuré. Ton pipeline en aval crashe parce qu'il attend du JSON.

Avec "any" ou forced selection, Claude est physiquement contraint d'appeler un tool. Pas de prose possible. C'est une garantie architecturale, pas une suggestion.
Pourquoi on envoie les deux tools même avec forced selection

Tu pourrais te demander : si on force extract_ipid, pourquoi envoyer aussi extract_guarantee_table ? 
En pratique, Claude a besoin de voir le schéma du tool qu'il va appeler, mais envoyer les deux ne coûte que quelques tokens de plus et ça rend le code plus simple. 
L'alternative serait de filtrer dynamiquement les tools — complexité inutile pour un gain minimal.

### Le pattern du mock dans les tests

Regarde comment on teste sans jamais appeler l'API :


```python
mock_client = MagicMock()
mock_client.messages.create.return_value = self._mock_tool_response(...)

result = extract_document(..., client=mock_client)

# On vérifie même les arguments passés à l'API :
call_kwargs = mock_client.messages.create.call_args
assert call_kwargs.kwargs["tool_choice"] == {"type": "tool", "name": "extract_ipid"}
``` 
On injecte un mock_client à la place du vrai Anthropic(). Le mock retourne exactement la réponse qu'on configure. 

### Résultat : 
tests déterministes, gratuits, et rapides. C'est le pattern standard pour tester du code qui dépend d'une API externe. Dans tes entretiens, si on te demande "comment tu testes un pipeline LLM", c'est cette réponse.


## Étape 4 : Validation sémantique

L'exam guide (Task 4.4) fait une distinction cruciale : 
**le schéma JSON élimine les erreurs de syntaxe, mais PAS les erreurs sémantiques.**

Voici des exemples concrets avec nos documents d'assurance :

| Type d'erreur | Exemple | Détecté par le schéma ? |
|---------------|---------|--------------------------|
| Syntaxe | JSON mal formé, accolade manquante | Oui (éliminé par tool_use) |
| Sémantique | percentage: 200 alors que le doc dit "100% BR-SS" | Non |
| Sémantique | Un benefit listé dans "Dentaire" mais category = "optical" | Non |
| Sémantique | has_comfort_pack: true mais comfort_pack_options: null | Non |
| Sémantique | madelin_eligible: true alors que le doc ne le mentionne pas | Non |

### C'est le rôle de la couche de validation qu'on va construire maintenant.

Commande — Remplis src/structured_extraction/validation.py :

Commande — Maintenant les tests de validation : tests/test_validation.py 

Commande — Lance tous les tests :
```bash 
uv run pytest tests/ -v
``` 
On devrait être à environ 130-140 tests maintenant. Partage-moi le résultat !

**Résaultats** : 
129 tests verts, pipeline solide ! On a maintenant les 3 premières couches : Schémas → Extraction → Validation. Il est temps de connecter la validation à l'extraction avec la boucle de retry.

## Retour pédagogique sur l'Étape 4 : Validation sémantique

### Les deux couches de défense

Visualise le pipeline comme un entonnoir de qualité :
```
Document texte
     │
     ▼
┌─────────────────────────────────────────┐
│  Couche 1 : tool_use + JSON schema      │  ← Élimine les erreurs de SYNTAXE
│  "Le JSON est-il bien formé ?"          │     (garanti par constrained decoding)
│  Résultat : JSON toujours valide        │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│  Couche 2 : Validation sémantique       │  ← Détecte les erreurs de SENS
│  "Les données sont-elles cohérentes ?"  │     (règles métier explicites)
│  Résultat : ValidationResult            │
└─────────────────────┬───────────────────┘
                      │
                      ▼
              is_valid == True ?
              ├── OUI → résultat final
              └── NON → retry avec feedback (Étape 5)
```

### Pourquoi has_retryable_errors est crucial (Task 4.4)

C'est un concept d'exam. L'exam guide dit textuellement : "retries are ineffective when the required information is simply absent from the source document".

Imagine : tu extrais un IPID qui ne mentionne pas le numéro SIRENE de l'assureur. La validation détecte que insurer_registration est null. Faut-il retenter l'extraction ? Non — l'info n'est tout simplement pas dans le document. Renvoyer le document à Claude 3 fois ne fera pas apparaître l'info magiquement, ça coûtera juste 3x plus cher.

En revanche, si Claude a mis percentage: null alors que le document dit clairement "100% BR-SS", c'est une erreur de parsing — un retry avec le feedback "tu as oublié d'extraire le pourcentage de la raw_value" a de bonnes chances de corriger le problème.

C'est pour ça qu'on distingue MISSING_CONTENT (pas retryable) des autres catégories (retryable) :
```python
@property
def has_retryable_errors(self) -> bool:
    return any(
        e.category != ValidationErrorCategory.MISSING_CONTENT
        for e in self.errors
    )
```

### Le format du feedback de retry

Regarde comment get_feedback_for_retry() construit un message structuré :
```bash 
The following validation errors were found in your extraction:
- [ERROR] benefits[0].reimbursement.percentage: Percentage is null. Suggestion: Extract the percentage from raw_value.
- [ERROR] comfort_pack_options: has_comfort_pack is True but options is empty.

Please re-extract the document, correcting these specific issues.
``` 
Ce feedback est chirurgical : 
il donne le chemin exact du champ (benefits[0].reimbursement.percentage), le problème, et une suggestion. Claude peut alors se concentrer sur ces points précis au lieu de refaire toute l'extraction à l'aveugle. C'est le pattern "retry-with-error-feedback" de l'exam (Task 4.4).

## Étape 5 : Retry with feedback

### On va maintenant construire la boucle de retry qui connecte extraction et validation.

Commande — Remplis src/structured_extraction/retry.py :

Commande — Les tests pour le retry : tests/test_retry.py

Commande — Lance tous les tests :

uv run pytest tests/ -v

### Résultats des tests : 
144 tests verts, le pipeline extraction → validation → retry est solide ! On entre maintenant dans les couches qui font briller ce projet auprès des recruteurs : le confidence scoring et le few-shot prompting.

## Retour pédagogique sur l'Étape 5 : Retry with feedback
### Le flux de la boucle de retry visualisé
```
Attempt 1                          Attempt 2 (retry)
─────────                          ─────────────────
Prompt: "Extract from              Prompt: "You previously extracted...
this document..."                  VALIDATION ERRORS:
     │                             - [ERROR] exclusions: responsible_contract
     ▼                               is True but no 'regulatory' exclusions
Claude API → tool_use              - PREVIOUS EXTRACTION:
     │                               { "exclusions": [{"type": "absolute"}] }
     ▼                             - ORIGINAL DOCUMENT:
Pydantic validate                    (full text again)
     │                             Fix these specific issues."
     ▼                                  │
ValidationResult:                       ▼
  is_valid: False                  Claude API → tool_use (corrigé)
  errors: [consistency]                 │
  has_retryable: True ──────────►       ▼
                                   ValidationResult:
                                     is_valid: True ✓ → terminé
```

### Pourquoi le retry prompt contient les 3 éléments

Le retry prompt contient toujours :

1. Les erreurs de validation — C'est le feedback chirurgical. Sans ça, Claude referait exactement la même extraction (ou une variation aléatoire). Avec les erreurs, il sait exactement quoi corriger. C'est le cœur du pattern "retry-with-error-feedback" de l'exam.

2. L'extraction précédente — Claude voit ce qu'il a produit. Il n'a pas besoin de tout refaire, juste de corriger les points signalés. Ça réduit le risque de régressions (corriger un champ mais en casser un autre).

3. Le document original — Indispensable ! Le document est la source de vérité. Sans lui, Claude ne pourrait pas vérifier ses corrections. On le remet à chaque retry.

### Le coût réel des retries

Chaque retry est un appel API complet. Avec notre config par défaut (max_retries=2), le pire cas est 3 appels. Si un appel Haiku coûte ~$0.002, le pire cas est ~$0.006 par document. C'est négligeable comparé au gain de qualité. Mais pour un batch de 10 000 documents, ça se cumule — d'où l'importance de retry_only_on_retryable qui évite les retries inutiles sur du contenu absent.


## Étape 6 : Few-shot prompting + Confidence scoring

On regroupe ces deux étapes parce qu'elles sont liées : les few-shot examples améliorent la qualité et la calibration de la confidence.

### Pourquoi les few-shot examples (Task 4.2)

L'exam guide dit : "Few-shot examples as the most effective technique for achieving consistently formatted, actionable output when detailed instructions alone produce inconsistent results".

Nos documents d'assurance ont des formats très variés. Le barème "Equilibre 1" écrit "100 % BR - SS", un autre pourrait écrire "100% BR-SS" ou "BR moins SS : 100%". 
Les few-shot examples montrent à Claude comment normaliser ces variations vers notre schéma uniforme.

Commande — Remplis src/structured_extraction/few_shot.py :

Commande — Remplis src/structured_extraction/confidence.py :

Commande — Tests pour confidence et few-shot : tests/test_confidence.py

Commande — Tests pour few-shot : tests/test_few_shot.py 

Commande — Lance tous les tests :

uv run pytest tests/ -v

### résultats des tests 
176 tests verts ! On est à plus de la moitié du projet et la base est ultra-solide. Il nous reste les couches "vitrine" — celles qui montrent une vraie maturité architecturale.

## Retour pédagogique sur l'Étape 6 : Confidence & Few-shot

### Le problème que le confidence scoring résout (Task 5.5)

Imagine que tu fais tourner le pipeline sur 500 documents APICIL et tu obtiens 97% d'accuracy globale. 
Ton manager dit "super, on automatise tout !". Mais en creusant :

    product_name:           99.8% accuracy  ← facile, toujours en gros en haut du doc
    insurer_name:           99.5% accuracy  ← idem
    insurer_registration:   72.0% accuracy  ← parfois absent, parfois mal parsé
    eligible_population:    68.0% accuracy  ← formulations très variables

Le 97% global masque que 2 champs sont catastrophiques. L'exam guide dit exactement ça : "aggregate accuracy metrics (e.g., 97% overall) may mask poor performance on specific document types or fields".

**C'est pourquoi on a construit AccuracyTracker avec un tracking par champ ET par type de document.**

En entretien, pouvoir expliquer pourquoi un score agrégé est dangereux et montrer ton code qui le décompose, c'est du niveau senior.

### Le flux de routing human review
```
Extraction terminée avec field_confidences
          │
          ▼
    route_for_review()
          │
          ├── Tous les champs HIGH → AUTO_ACCEPT (pas de review)
          ├── Au moins un MEDIUM  → HUMAN_REVIEW (vérification ciblée)
          └── Au moins un LOW     → HUMAN_REVIEW (prioritaire)
          
    Le reviewer ne vérifie QUE les champs flaggés, pas tout le document.
    → Optimise la capacité limitée des reviewers humains.
``` 

### Pourquoi le reasoning dans les few-shot examples

Nos examples ne montrent pas seulement input → output. Ils incluent un reasoning qui explique pourquoi :
```bash
"reasoning": "insurer_registration is null because no SIRENE number is mentioned.
CRITICAL: we return null, NOT a guessed value."
```

L'exam guide (Task 4.2) dit : "few-shot examples enable the model to generalize judgment to novel patterns rather than matching only pre-specified cases". 
Le reasoning enseigne la logique de décision, pas juste le mapping. Quand Claude rencontre un nouveau document avec un format jamais vu, il applique la logique, pas du pattern matching.


## Étape 7 : Quality Review (instance indépendante) + Batch Processing

On combine ces deux modules parce qu'ils sont plus légers et qu'ensemble ils bouclent le pipeline. 

Le quality review est un concept d'exam important (Task 4.6), et le batch processing (Task 4.5) c'est ton pain quotidien en tant que data engineer.

### Pourquoi une instance indépendante pour la review (Task 4.6)

L'exam guide est explicite : "a model retains reasoning context from generation, making it less likely to question its own decisions in the same session". 

Si Claude extrait des données et qu'on lui demande ensuite "vérifie ton extraction", il va avoir un biais de confirmation — il se souvient pourquoi il a fait ces choix et va les justifier. 

**Une instance séparée, sans le contexte de l'extraction, est plus objective.**

Commande — Remplis src/structured_extraction/review.py :

Commande — Remplis src/structured_extraction/batch.py :

Commande — Tests pour review et batch : tests/test_review.py   et tests/test_batch.py

Commande — Lance tous les tests :

uv run pytest tests/ -v

### Résultats des tests 
206 tests verts ! On approche de la ligne d'arrivée. Il nous reste deux étapes pour boucler le projet : le script de démo (pour que les recruteurs voient le pipeline en action) et le README vitrine.

## Retour pédagogique sur l'Étape 7 : Review & Batch

### La séparation des instances (Task 4.6) — pourquoi c'est un concept fondamental

Imagine un développeur qui écrit du code puis fait sa propre code review. Il va inconsciemment justifier ses choix parce qu'il se souvient de son raisonnement. C'est exactement pareil pour Claude.
```
Instance 1 (Extraction)              Instance 2 (Review)
─────────────────────────            ─────────────────────
System: "Extract data..."           System: "You are an independent reviewer.
                                     You did NOT perform the extraction."
User: "Voici le document..."
                                    User: "Voici le document ORIGINAL
Response: { extraction... }          + l'extraction À VÉRIFIER"
   │
   │ ← Contexte de raisonnement     Aucun contexte partagé !
   │   (pourquoi j'ai mis            Le reviewer est "frais",
   │    madelin_eligible=True)        sans biais de confirmation.
```
L'instance de review ne sait pas pourquoi l'extraction a fait ses choix. Elle compare froidement le document source et l'extraction. 
Si madelin_eligible: true mais que le document ne mentionne jamais "Madelin", le reviewer le détecte sans hésitation — alors que l'instance d'extraction aurait tendance à justifier son choix.

### Le Message Batches API — quand l'utiliser et quand NE PAS l'utiliser (Task 4.5)

C'est une question d'exam classique (voir Question 11 dans l'exam guide). La règle est simple :
```
Workflow bloquant                    Workflow non-bloquant
(développeur attend le résultat)     (traitement nocturne/hebdo)
         │                                    │
         ▼                                    ▼
    API synchrone                     Message Batches API
    Latence: ~2-5s                    Latence: jusqu'à 24h
    Coût: plein tarif                 Coût: -50%
```
Notre pipeline d'extraction de documents d'assurance est un cas parfait pour le batch : ton pote courtier a un lot de documents à traiter, il n'a pas besoin du résultat dans la seconde. Il lance le batch le soir, les résultats sont prêts le matin.

Le point critique : la Batches API ne supporte pas le multi-turn tool calling dans un seul request. 
Chaque document doit être traitable en un seul appel. 
Notre pipeline est justement conçu comme ça : un document → un appel → une extraction. Parfait pour le batch.

### Le custom_id — un détail critique pour la production

Quand tu soumets 500 documents en batch, les résultats ne reviennent pas forcément dans l'ordre. Le custom_id est le seul lien entre ta requête et sa réponse. 
En cas d'échec partiel (200 succès, 5 échecs), tu identifies les échecs par custom_id et tu resoumets seulement ceux-là, potentiellement avec des modifications (ex: document trop long → on le chunke).

## Étape 8 : Script de démo + Metrics + README

On va d'abord compléter le module metrics (léger), puis créer le script de démo qui fait tourner le pipeline complet, et enfin écrire le README vitrine.

Commande — Remplis src/structured_extraction/metrics.py :

Commande — Remplis src/structured_extraction/__init__.py pour exposer l'API publique :

Commande — Crée le script de démo scripts/extract_single.py :

Commande — Test rapide du metrics module : tests/test_metrics.py 

Commande — Lance tous les tests + le dry run de la démo :
```bash
uv run pytest tests/ -v
echo "---"
uv run python scripts/extract_single.py
```
### résultats des tests et du dry run 
211 tests verts et le dry run montre parfaitement le pipeline de bout en bout ! C'est exactement ce qu'un recruteur veut voir : un pipeline clair, étape par étape, avec la logique expliquée.

On passe à la dernière étape : le README vitrine. C'est ce que les recruteurs lisent en premier sur ton repo GitHub. On va le structurer comme tes deux autres projets — avec l'architecture, les concepts de l'exam, les tradeoffs, et le domain coverage.

## Étape 9 : README 

Commande — Crée le README.md :

**Commande** — Vérifie que tout est toujours vert et fais un dernier check de la structure :

```bash
uv run pytest tests/ -v --tb=short
echo "---"
uv run ruff check src/ tests/
echo "---"
tree -I '__pycache__|.venv|.git|insurance_docs' -L 3
```

## Bilan final du projet
### Ce qu'on a construit ensemble
```bash 
structured-data-extraction/
├── 12 modules Python         (src/structured_extraction/)
├── 11 fichiers de tests       (tests/)
├── 211 tests                  (100% verts, 0 appel API, 0.38s)
├── 0 erreurs ruff             (lint + format clean)
├── 1 script de démo           (dry run + live mode)
├── 1 README vitrine           (architecture, tradeoffs, domain coverage)
├── CLAUDE.md + rules/         (Claude Code config avec path-scoping)
└── Makefile                   (workflow shortcuts)
``` 

### Le pipeline de bout en bout

    PDF → Document Loader → Extraction (tool_use) → Validation (sémantique)
        → Retry avec feedback → Confidence scoring → Human review routing
        → Independent quality review → Batch processing (50% savings)

### Couverture des Task Statements de l'exam
| Task Statement | Concept | Où dans le code |
|----------------|---------|-----------------|
| 4.1 | Critères explicites dans les prompts | extraction.py — EXTRACTION_SYSTEM_PROMPT |
| 4.2 | Few-shot pour formats variés | few_shot.py — 4 examples avec reasoning |
| 4.3 | tool_use + JSON schema + nullable + enum "other" | schemas.py, extraction.py (tool_choice) |
| 4.4 | Retry-with-error-feedback + limites du retry | retry.py, validation.py (has_retryable_errors) |
| 4.5 | Message Batches API + custom_id + SLA | batch.py (50% savings, failure resubmission) |
| 4.6 | Instance indépendante pour review | review.py (separate system prompt, no context) |
| 5.5 | Confidence per field + accuracy tracking + sampling | confidence.py (routing, AccuracyTracker, stratified) |

### Ce que tu peux expliquer en entretien

Voici les 5 questions qu'un recruteur pourrait te poser sur ce projet, et les réponses que tu as maintenant :

"Pourquoi tool_use plutôt que demander du JSON en prose ?" 
→ Le tool_use avec JSON schema utilise la constrained decoding 
— Claude ne peut physiquement générer que des tokens qui respectent le schéma. Zéro erreur de syntaxe JSON, garanti. 
Les prompts "retourne du JSON" n'offrent pas cette garantie.

"Comment tu gères les cas où l'information n'est pas dans le document ?" 
→ Champs nullable. Si on rend un champ obligatoire, Claude est forcé d'inventer une valeur. Avec Optional[T] = None, il peut honnêtement dire "pas trouvé". Et on ne retente PAS l'extraction pour du contenu absent 
— has_retryable_errors distingue les erreurs corrigeables (format, cohérence) des erreurs non-corrigeables (info absente).

"Comment tu sais si ton pipeline est fiable ?" 
→ Accuracy tracking par champ ET par type de document, pas juste un score global. 
Un 97% global peut masquer un champ à 68%. 
Plus : stratified sampling pour mesurer le taux d'erreur sur les extractions auto-acceptées, et instance de review indépendante sans biais de confirmation.

"Comment tu scales ce pipeline ?" 
→ Message Batches API pour 50% de réduction de coût. Chaque document est un appel indépendant single-turn, donc compatible batch. Les échecs sont identifiés par custom_id et resoumis individuellement.

"Pourquoi 211 tests sans appeler l'API ?" 
→ Mock injection. On passe un mock_client au lieu du vrai Anthropic(). 
Le mock retourne exactement la réponse configurée. 
Tests déterministes, gratuits, rapides. On vérifie même les arguments passés à l'API (tool_choice, system prompt).

## Prochaines étapes suggérées

Pour continuer à enrichir ton portfolio après le push GitHub :

    - Tester en live avec ta clé API sur les vrais PDFs APICIL (uv run python scripts/extract_single.py chemin/vers/ipid.pdf)
    
    - Créer des labeled data (data/labeled/) avec les extractions manuelles de 5-10 documents, puis lancer run_evaluation.py pour mesurer l'accuracy réelle
    
    - Ajouter un schéma pour les tarifs (pricing) — ça montre que l'architecture est extensible
    
    - Connecter avec ton projet OpenClaw — le pipeline d'extraction alimente le RAG de l'assistant courtier
