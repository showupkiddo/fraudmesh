FraudMesh
Production-Grade Plan of Action
Federated Graph Neural Network framework for privacy-preserving detection of
mule-account and money-laundering rings
Phased execution plan  |  Model zoo  |  Dataset catalogue  |  Quality gates  |  Risk register
Team: Anvi Phadke, Dishant Shah, Divvya Jain, Pranav Vaghela
Project guide: Mr. Pankaj Sonawane  |  Department of Computer Engineering  |  AY 2026–27
Version 1.0  |  October 2026

FraudMesh — Production-Grade Plan of Action
Page 2
Contents
Section
What it covers
1. Executive summary
The plan in one page and the six upgrades over the current report
2. Design review
14 issues in the current design to resolve before writing code
3. Target architecture
Production view: tenant plane, federation plane, analyst plane
4. Model zoo
Every model you will build, what it is trained on, who owns it
5. Dataset catalogue
Links, sizes, labels, licences, and which model uses which dataset
6. Roadmap and ownership
16-week timeline and who leads each phase
7. Phases 0–14
Step-by-step instructions, deliverables, exit criteria, pitfalls
8. Quality gates
Test strategy across every layer
9. Risk register and MVP cut line
What can go wrong, and what to drop first if you fall behind
Appendix
Tool and documentation links, how links were verified
How to use this document
This is a plan, not code. Every phase tells you what to build, in what order, how to check it works, and when it is done.
You and your teammates write all the code. Phases overlap in the timeline but have a strict dependency order: do not
start a phase until the exit criteria of the phase it depends on are met, because later results are only meaningful if the
earlier layer is correct. Week numbers assume you start now (early October 2026), which puts week 16 in late January
2027. Shift the whole schedule to match your college's actual submission and viva dates.
What “production-grade” means here
A student project cannot be bank-production-ready: that needs penetration tests, regulatory approval, HSM-backed keys
and real data agreements. What this plan delivers is production discipline: versioned data, reproducible training, tested
components, gated model promotion, secured service boundaries, monitoring, runbooks and documented limits. That is
what a reviewer or interviewer will actually probe.

FraudMesh — Production-Grade Plan of Action
Page 3
1. Executive summary
FraudMesh detects mule rings that are spread across institutions, without any institution sharing raw transactions.
Each institution trains a graph attention model (TW-TR-GAT) on its own transaction graph; a coordinating server
combines the updates with a custom, reputation-weighted, poisoning-robust strategy (RAP-FedAvg); local training
is differentially private; analysts work through a web console. The current report defines the right ideas. This plan
turns them into a system that is reproducible, testable and defensible in a viva.
Six upgrades over the current report
1
Use IBM AMLworld as the primary dataset. It ships real ring-pattern labels and a bank column, so you
can partition by bank and get natural cross-institution edges. PaySim, IEEE-CIS and ULB cannot give you that
(see Section 2).
2
Build two stages, not one. A federated per-transaction scorer (trained on IEEE-CIS, BAF, PaySim, ULB,
which are tabular) feeds a federated graph model (trained on AMLworld, SAML-D, Elliptic++). This is how real
fraud stacks work and it makes every dataset useful.
3
Fix four architectural contradictions between “data never leaves” and a central inference API, a
server-side validation set, secure aggregation versus per-client reputation, and mismatched client schemas.
4
Correct three technical details in TW-TR-GAT (how temporal decay enters attention), in the DP claim (what
the privacy unit is on a graph) and in the evaluation (PR-AUC and temporal splits, not ROC-AUC on random
splits).
5
Add production scaffolding. Data versioning, experiment tracking, a model registry with promotion gates,
CI, container security, observability, drift monitoring, runbooks.
6
Define a cut line. Section 9 states what is must-have, what is should-have and what is stretch, so a slip in
week 9 does not sink the project.
The 15 phases at a glance
#
Phase
Output you can show
0
Foundation and engineering setup
Repo, CI, tracking, data versioning
1
Data acquisition, canonical schema, validation
Versioned, validated canonical datasets
2
Graph construction, labels, federated partitioning
Per-institution graphs; the “blind spot” table
3
Centralised baselines and evaluation harness
Numbers to beat; reproducible results tables
4
Plain federated pipeline (Flower, FedAvg)
Working FL in simulation and in containers with TLS
5
TW-TR-GAT
Custom model, tests, ablation ladder
6
RAP-FedAvg
Custom Flower strategy, poisoning defence
7
Differential privacy
Privacy ledger, epsilon sweep, membership-inference check
8
Full experiment campaign
All comparisons from the report, with statistics
9
Packaging, registry, serving
Per-institution inference API with gated model promotion
10
Data layer and feedback loop
Postgres, Neo4j, label write-back
11
FraudMesh web console
Five screens, auth, tenant-scoped, tested
12
Security, observability, reliability
Dashboards, drills, runbooks, model card
13
Integration and acceptance demo
Planted ring flagged end to end, automated
14
Documentation, report, viva
Report, reproducibility package, viva prep

FraudMesh — Production-Grade Plan of Action
Page 4
2. Design review: resolve these before coding
These are gaps between the current report and a system that holds up. None is fatal; each has a concrete fix.
Write each resolution as a short Architecture Decision Record (ADR) in Phase 0, so the final report can cite a
decision log.
#
Issue in the current design
Why it matters
Recommended resolution
1
ULB credit-card data has no
account or device IDs. It has
Time, Amount and 28 anonymised
PCA columns.
You cannot build a graph from it, so
the “ULB bank client” cannot take part
in graph training.
Use ULB only for the tabular stage-1 scorer
(Model M4).
2
IEEE-CIS has no
sender-to-receiver money flow.
It has card, address, email-domain
and device fields.
A graph built from shared attributes is
not a money-flow graph, and ring
labels you propagate yourself are an
artefact of your own labelling.
Use for M4. If you build an entity graph from
it, label it “shared-attribute graph” and
never mix it into ring metrics.
3
PaySim is synthetic and its
fraud logic is simple (fraud
occurs only in TRANSFER and
CASH_OUT types).
Rings derived by label propagation
are weakly justified; results will look
better than they should.
Keep as a secondary, UPI-style schema
exercise and for M4; report it as such.
4
Ring labels by propagation
across connected components.
Circular: your labels depend on your
own graph rule.
Use AMLworld pattern files, which label each
laundering instance (fan-in, fan-out, cycles,
scatter-gather and others) directly.
5
Clients with different feature
schemas cannot be averaged.
FedAvg needs identical tensor shapes.
A PaySim client and an IEEE-CIS client
have different inputs.
Primary FL experiment: one dataset
(AMLworld), one schema, partitioned by
bank. Optional: shared GNN trunk plus local,
non-aggregated input encoders.
6
Cross-institution edges are
invisible to a local graph.
The whole premise is rings spread
across banks. A local graph that drops
the other side loses the very signal
you want.
Each client keeps edges where either
endpoint is its own, with the remote
endpoint as a hashed stub node. Stretch:
private set intersection for entity linkage.
7
Temporal decay is multiplied
after softmax.
Attention no longer sums to 1, and a
free λ can go negative and amplify old
edges.
Apply decay as an additive term inside the
logit, λ = softplus(parameter) per head, Δt
normalised. Mask future edges (causal).
8
Prediction granularity is
inconsistent (node classifier, but
AMLworld labels transactions).
Heads, losses and metrics must agree
on the unit being scored.
Define three heads: edge (transaction),
account (derived label), ring (group).
Document how account labels are derived.
9
DP-SGD on graphs. A node's loss
depends on its neighbours, so
per-example gradients are not
independent.
Standard sample-level epsilon
under-counts leakage. Opacus also
rejects BatchNorm and needs
per-sample support in custom layers.
Define the privacy unit explicitly (one
degree-capped ego-subgraph per example),
use Poisson sampling, state the claim
honestly, validate per-sample gradients.
10
Reputation needs a server-side
validation set and plaintext
per-client updates.
That is centralised data at the server,
and it conflicts with secure
aggregation.
Use a neutral held-out synthetic slice no
client trains on; state the trust model in an
ADR; do not claim secure aggregation
together with per-client reputation.
11
Single central Inference API.
To score a transaction it needs the
transaction graph, which contradicts
“data never leaves”.
Run inference beside each institution’s data
(model goes to data). The console is
tenant-scoped; the consortium dashboard
shows aggregates only.
12
ROC-AUC on a random split with
about 1 laundering transaction per
800–2000.
ROC-AUC looks excellent on extreme
imbalance; random splits leak time.
Primary metric PR-AUC and minority-class
F1; precision@k; ring recall; chronological
splits; 5+ seeds with confidence intervals.
13
Analyst feedback loop is
biased. Only flagged items get
labels.
The next round trains on a skewed
sample and can reinforce its own blind
spots.
Keep a random audit sample of un-alerted
transactions for review; record label
provenance and delay.
14
“FedFraud’s method” as a
baseline requires re-implementing
a paper.
Underspecified papers give unfair or
wrong baselines.
Re-implement from the paper, document
assumptions, call it “FedFraud-style”, and
budget a week.

FraudMesh — Production-Grade Plan of Action
Page 5
3. Target architecture (production view)
The principle is the model goes to the data, never the data to the model. Three planes with different trust
levels:
TENANT PLANE (data stays)
FEDERATION PLANE (weights only)
ANALYST PLANE
Institution A (bank)
Graph store + Postgres
Local TW-TR-GAT + DP-SGD
Inference service + FL client
Institution B (UPI fintech)
Graph store + Postgres
Local TW-TR-GAT + DP-SGD
Inference service + FL client
Institution C (NBFC)
Graph store + Postgres
Local TW-TR-GAT + DP-SGD
Inference service + FL client
Flower aggregation server
RAP-FedAvg strategy
Update sanitiser, reputation
Model registry (MLflow)
candidate, staging, prod
Gated promotion, rollback
Privacy ledger
epsilon, delta, sigma per round
Append-only
FraudMesh console
Alert queue, Graph explorer
Case workflow, Reports
Tenant-scoped, RBAC
Consortium dashboard
Rounds, reputation, epsilon
Aggregates only
Tenant consoles and inference run beside each institution's own data; links between planes carry weights and aggregate metrics only (mutual TLS).
Component
Responsibility
Key design rule
Tenant stack (one
per institution)
Graph store, relational store, graph builder, inference
service, FL client, tenant console backend
Nothing in it is reachable from another
tenant; network isolation is tested
Aggregation server
Runs RAP-FedAvg, sanitises updates, tracks reputation,
checkpoints every round
Sees weights and metrics only; resumable
from checkpoint
Model registry
Versioned artefacts with config, feature spec, data hash,
metrics, DP summary
Promotion gates: beat production on
validation, pass latency and smoke tests;
one-click rollback
Privacy ledger
Append-only record of (client, round, epsilon, delta,
sigma, clip, sampling rate, steps)
Training stops for a client whose budget is
spent
Inference service
Scores transactions, assembles causal sub-graphs,
scores candidate rings, explains alerts
Uses the same feature code as training;
parity-tested
Consortium
dashboard
Rounds, reputation weights, epsilon,
accuracy-versus-epsilon
Reads aggregate endpoints only; schema
has no account or transaction columns
Observability
Structured logs, metrics, dashboards, drift monitors,
alerts
Every service exposes health, readiness
and metrics endpoints

FraudMesh — Production-Grade Plan of Action
Page 6
4. Model zoo
You will build several models. None is tied to one dataset: each has a primary dataset for training, and secondary
datasets for validation, out-of-distribution testing or schema-generalisation checks. Model IDs are used throughout
the phases.
ID
Model and task
Architecture
Train on
Validate / test on
Federated?
Lead
M
1
Strong non-neural
baseline. Edge
(transaction)
classification with
graph-derived
features.
LightGBM or XGBoost
on edge features plus
degree, fan-in/out,
cycle and
scatter-gather counts
AMLworld HI-Small,
LI-Small (later
Medium)
Chronological
val/test; SAML-D as
out-of-distribution
Centralised
reference only
Anvi
M
2
GNN baselines.
Edge and account
classification.
GraphSAGE, GAT, GIN
or PNA with edge
features, directed
message passing,
neighbour sampling
AMLworld HI-Small,
LI-Small
Chronological
val/test; SAML-D,
Elliptic++ (node
task) as
out-of-distribution
Centralised,
local-only and
FedAvg variants
Dishant
M
3
Core model.
TW-TR-GAT with
edge, account and
ring heads.
3 layers, hidden 128,
4 heads, relational
edge encoder, causal
temporal decay, ring
readout
AMLworld
(partitioned by
bank); then
SAML-D; PaySim for
UPI-style schema
Ring-level metrics
on held-out rings;
Elliptic++ for
out-of-domain node
task
Yes: FedAvg,
then
RAP-FedAvg,
then with DP
Dishant,
Divvya
M
4
Stage-1 transaction
risk scorer. Fast
per-transaction
filter.
LightGBM reference;
MLP (or Flower tree
strategy) for the
federated version
IEEE-CIS (clients by
ProductCD), BAF
variants, PaySim,
ULB (each
separately)
Time-based splits
(IEEE-CIS
TransactionDT, BAF
month)
Yes, within each
dataset family
Anvi, Divvya
M
5
Calibrator and
ensemble.
Combines M4 and
M3 scores into one
calibrated alert
score.
Isotonic or Platt
calibration, optionally
a small logistic stacker
Validation split of
AMLworld clients
Held-out test
windows
Per institution
(local
thresholds)
Pranav
M
6
Explainer for the
console. Which
edges and patterns
drove an alert.
Attention export plus
GNNExplainer-style
edge importance plus
rule-based motif tags
Uses trained M3, no
extra training data
Qualitative review
on planted and
ground-truth rings
Local per
institution
Dishant,
Pranav
Why a two-stage design
A per-transaction scorer is cheap and catches isolated fraud (stolen card, account takeover). The graph model is
expensive and only worth running on neighbourhoods that look suspicious. Real systems chain them. It also solves your
dataset problem honestly: tabular datasets train M4, graph datasets train M3, and neither is forced to impersonate the
other.

FraudMesh — Production-Grade Plan of Action
Page 7
5. Dataset catalogue
Priority P0 means you need it for the core result. P1 adds generalisation and the stage-1 model. P2 is optional.
Links marked [verified] were opened and confirmed while preparing this plan. For the others the URL and figures
come from standard references and should be confirmed on first visit; Kaggle slugs rarely change but numbers in
dataset cards occasionally do.
Dataset
Tier
Size and shape
Labels
Use in FraudMesh
IBM AMLworld
(HI/LI x Small/Medi
um/Large)
P0
Small: about 5.1M (HI) / 6.9M (LI)
transactions over about 0.5M / 0.7M
accounts. Medium: about 31M. Large:
about 176–180M (skip). Columns:
timestamp, from bank, account, to
bank, account, amounts, currencies,
payment format.
Per-transaction
laundering flag, plus a
separate patterns file
listing each laundering
instance. About 1
laundering transaction
per 800–2000.
Primary graph dataset for M1,
M2, M3, partitioned by bank.
Ring ground truth. HI to LI
generalisation.
SAML-D
P1
About 9.5M transactions (per its
dataset card); sender and receiver
accounts, amounts, currencies,
locations, payment types.
Suspicious flag plus a
typology column
covering many
laundering types.
Second generator for
out-of-distribution tests of M1,
M2, M3. Schema-adapter stress
test.
PaySim
P1
About 6.36M rows, 11 columns, about
0.13% fraud; simulated mobile-money
(UPI-style) with origin and destination
names.
Fraud flag (only in
TRANSFER and
CASH_OUT).
UPI-style schema exercise for
M3; tabular M4. Treat ring
labels as weak.
IEEE-CIS Fraud
Detection
P1
Train: about 590k transactions x 394
columns, plus identity table of about
144k rows. About 3.5% fraud.
Transaction-level fraud
flag.
M4 only. Natural clients by
ProductCD. Time split on
TransactionDT.
BAF (Bank
Account Fraud,
NeurIPS 2022)
P1
Six variants of 1M rows each, 30
features, about 1% fraud, with a
month column.
Application-level fraud
flag.
M4 federated across variants
(controlled distribution shift);
drift-monitoring demo using
month.
ULB Credit Card
Fraud
P1
284,807 transactions over two days,
492 frauds (0.17%); Time, Amount, 28
PCA columns.
Fraud flag.
M4 sanity benchmark only. No
graph.
Elliptic (Bitcoin
transactions)
P2
203,769 transaction nodes, 166
features, 49 time steps; 4,545 illicit.
Illicit, licit, unknown.
Out-of-domain node-level test
for M2 and M3.
Elliptic++
P2
203k transactions and 822k wallet
addresses, about 1.27M address
interactions; 14,266 illicit wallets.
Illicit labels on
transactions and
wallets.
Richer graph for out-of-domain
tests and heterogeneous-graph
experiments.
Direct links
Dataset
Link
Status
IBM AMLworld (Kaggle)
https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-mone
y-laundering-aml
[verified]
AMLworld paper (generator,
pattern definitions)
https://arxiv.org/abs/2306.16424
[verified]
Elliptic++ (GitHub, with
download instructions)
https://github.com/git-disl/EllipticPlusPlus
[verified]
Elliptic (Kaggle)
https://www.kaggle.com/datasets/ellipticco/elliptic-data-set
confirm on visit
SAML-D (Kaggle)
https://www.kaggle.com/datasets/berkanoztas/synthetic-transaction-monitoring
-dataset-aml
confirm on visit
PaySim (Kaggle)
https://www.kaggle.com/datasets/ealaxi/paysim1
confirm on visit
IEEE-CIS Fraud Detection
(Kaggle competition)
https://www.kaggle.com/c/ieee-fraud-detection
confirm; accept
rules to download
BAF, Bank Account Fraud
(Kaggle)
https://www.kaggle.com/datasets/sgpjesus/bank-account-fraud-dataset-neurips
-2022
confirm on visit

FraudMesh — Production-Grade Plan of Action
Page 8
Dataset
Link
Status
ULB Credit Card Fraud (Kaggle)
https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud
confirm on visit
IBM AMLSim (generator, for
planting custom rings)
https://github.com/IBM/AMLSim
confirm on visit
IBM Multi-GNN (reference GNN
baselines for AMLworld)
https://github.com/IBM/Multi-GNN
confirm on visit
Which dataset feeds which model
Dataset
M1
M2
M3
M4
M5
Role
AMLworld HI-Small / LI-Small
Train
Train
Train
—
Calibrate
Primary; HI to LI
generalisation
AMLworld Medium
Scale
Scale
Scale
—
—
Only if compute allows
SAML-D
OOD
test
OOD test
Train and OOD
—
—
Second generator
PaySim
—
—
Schema
exercise
Train
—
UPI-style
IEEE-CIS
—
—
—
Train
—
Clients by ProductCD
BAF variants
—
—
—
Train
—
Shift and drift demo
ULB
—
—
—
Benchma
rk
—
Sanity only
Elliptic / Elliptic++
—
OOD test
OOD test
—
—
Out-of-domain node task
Download hygiene
Create a Kaggle API token once and keep it out of the repository. For IEEE-CIS you must accept the competition rules in
the browser before the download works. Read each licence and write it into the dataset card in Phase 1: some Kaggle
datasets restrict commercial use or redistribution, which matters if you ever open-source the repo. Do not commit raw
data; version it with DVC and record its SHA-256.

FraudMesh — Production-Grade Plan of Action
Page 9
6. Roadmap and ownership
Sixteen weeks, with overlap where work is independent. The web console and data layer start while experiments
run, because they depend on the API contract, not on final model quality. Ownership follows the split in the
current report; “L” leads, “S” supports and reviews.
Phase
1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
0 Foundation
1 Data and schema
2 Graphs and partitions
3 Baselines and harness
4 Plain FL pipeline
5 TW-TR-GAT
6 RAP-FedAvg
7 Differential privacy
8 Experiment campaign
9 Packaging and serving
10 Data layer and feedback
11 Web console
12 Hardening
13 Integration and demo
14 Docs, report, viva
Colour key: navy = engineering and documentation, teal = data and evaluation, purple = research components, amber = product
and serving.
Ownership matrix
Phase
Anvi
Dishant
Divvya
Pranav
0 Foundation
S
S
S
L
1 Data and schema
L
S
S
S
2 Graphs and partitions
L
S
S
—
3 Baselines and harness
L
L (GNN baselines)
S
—
4 Plain FL pipeline
S
S
L
S
5 TW-TR-GAT
S
L
S
—
6 RAP-FedAvg
S
—
L
—
7 Differential privacy
—
S
L
—
8 Experiment campaign
L
S
S
—
9 Packaging and serving
S
S
—
L
10 Data layer and feedback
S
—
—
L
11 Web console
—
—
—
L
12 Hardening
S
S
S
L
13 Integration and demo
S
S
S
L
14 Docs, report, viva
L
S
S
S
Weekly rhythm: Monday 30-minute planning, mid-week pair review of open pull requests, Friday demo to the guide (even if only a
plot or a screenshot). Every Friday the main branch must be green in CI.

FraudMesh — Production-Grade Plan of Action
Page 10
7. The phases
Each phase uses the same layout: goal, why it matters, numbered steps, deliverables, exit criteria and pitfalls.
Steps are written as instructions to the person leading the phase.
PHASE 0
Foundation and engineering setup
Timeline: Week 1
Owners: Pranav (lead), all
Goal
A repository where any teammate can clone, run the tests and reproduce a toy training run with one documented
command.
Why this matters
Everything later depends on reproducibility. If experiments are not tied to a code version, a data version and a
config, you cannot defend a single number in the viva. Setup time spent now is repaid every week.
Step-by-step instructions
1
Choose one monorepo. Top-level packages: data, graph, models, federated, privacy, serving, console,
infra, experiments, docs, tests. Install the Python package in editable mode so every module imports the
same code (this is what makes training/serving feature parity possible later).
2
Pin the environment. Fix one Python version and lock exact versions of PyTorch, CUDA build, PyTorch
Geometric, Opacus and Flower. PyG wheels are tied to the torch and CUDA pair, so version drift is the most
common cause of lost days. After the first clean install, record the working combination in a COMPATIBILITY
file and do not upgrade mid-project.
3
Decide the compute plan. Develop on CPU with a tiny fixture dataset. For real runs, list your GPU options
(college lab, Kaggle or Colab notebooks, cloud credits) and choose where “official” experiment runs happen.
Run those inside the same container image used in CI.
4
Set the Git workflow. Protected main, short-lived branches, pull request required, one reviewer minimum,
CODEOWNERS per module, conventional commit messages.
5
Add quality gates. Pre-commit hooks (linter, formatter, type-checker on core packages), a test runner with
a coverage floor, and a CI pipeline that on every pull request runs lint, type-check, unit tests and builds the
Docker images.
6
Centralise configuration. Use a hierarchical config system (Hydra or OmegaConf). Every experiment must
be fully described by a config file plus the git SHA plus the data version. No hard-coded paths, seeds or
hyperparameters in code.
7
Stand up experiment tracking. Run an MLflow tracking server in Docker. Agree a naming convention
(phase, model ID, dataset, partition, seed). Log parameters, per-round metrics, artefacts, git SHA and data
hash.
8
Version the data. Set up DVC with a remote (an external drive, MinIO or cloud storage). Raw data is
read-only; every processed dataset is the output of a named DVC stage so it can be rebuilt.
9
Start a decision log. Create docs/adr and write one ADR for each of the 14 items in Section 2, even if the
first version is two lines. Add a weekly engineering log.
10 Create the project board. One issue per phase deliverable, labelled by owner and phase. Link pull requests
to issues.

FraudMesh — Production-Grade Plan of Action
Page 11
Deliverables
Exit criteria (definition of done)
•
Repository skeleton with CI green
•
COMPATIBILITY file and environment lock
•
MLflow server (compose file) and DVC remote
•
ADR folder with 14 initial ADRs
•
Project board populated
•
Fresh clone to passing tests in under 15 minutes following
the README
•
A toy run appears in the MLflow UI with git SHA and config
•
CI blocks a deliberately broken pull request
Pitfalls to watch for
Secrets in the repository (use an ignored .env, enable secret scanning, rotate anything that leaks). Letting each member
keep a private environment. Skipping type checks on the data adapters, where silent dtype errors are most costly.
PHASE 1
Data acquisition, canonical schema and
validation
Timeline: Weeks 2–3
Owners: Anvi (lead), Pranav (schema
review)
Goal
Validated, versioned canonical datasets for every P0 and P1 source, each with a data card and a tested adapter.
Why this matters
Datasets arrive in different shapes, currencies and time formats. A single canonical schema with one adapter per
source is what lets one model code path run on AMLworld, SAML-D and PaySim, and it is the basis for the
cross-dataset evidence you want.
Step-by-step instructions
1
Get access. Create the Kaggle token, accept the IEEE-CIS competition rules, and note each dataset’s licence
in a table.
2
Download in priority order. P0: AMLworld HI-Small and LI-Small, including the patterns files. P1: PaySim,
SAML-D, BAF, IEEE-CIS, ULB. P2: Elliptic, Elliptic++, AMLworld Medium. Skip AMLworld Large unless you get a
proper compute allocation. Store under data/raw/<dataset>, record SHA-256, mark read-only.
3
Write a data card per dataset. Source URL, download date, licence, row and column counts, label
definition, known quirks, intended use, what it must not be used for.
4
Run exploratory analysis per dataset. Label rate, time span and timestamp resolution, account degree
distribution, currency and format mix, duplicates, missingness. Compare against published statistics; a
mismatch means a bad download or a parse bug.
5
Define the canonical transaction schema (ADR). Fields: transaction id, UTC timestamp, source account,
destination account, source institution, destination institution, amount in a base currency (original amount
and currency retained), channel (enumerated), plus label fields: edge label, ring id (nullable), typology
(nullable). Dataset-specific extras live in a side table.
6
Pseudonymise identifiers. Hash account IDs with a keyed hash so the same account yields the same ID in
every client. Without this, cross-institution linkage is impossible. Keep the key out of the repository.
7
Write one adapter per dataset. Pure functions from raw files to canonical Parquet, each tested on a
1,000-row sample. Handle AMLworld’s multiple currencies with a fixed, documented rate table, and decide
explicitly whether to use amount paid or received.
8
Define the tabular view for M4. For IEEE-CIS, BAF, PaySim and ULB, list the features you will use, how
time-based features are built, and how entity keys (card, device, account) are used for velocity features. ULB
has only Time, Amount and PCA columns, so it stays a standalone benchmark.
9
Add data validation suites. Use Pandera or Great Expectations: types, non-negative amounts, non-null
keys, timestamp bounds, referential integrity, labels in {0,1}. Run against the sample in CI and against the
full data in the pipeline; fail loudly.
10 Audit for leakage. List every column that could reveal the label (for example PaySim’s isFlaggedFraud) and
drop it. Compute all history-based features strictly as-of the transaction time.
11 Use a columnar engine. Read and transform large CSVs with Polars or DuckDB in chunks, write partitioned
Parquet, and register the whole thing as a DVC stage.

FraudMesh — Production-Grade Plan of Action
Page 12
Deliverables
Exit criteria (definition of done)
•
Raw and canonical data for P0 and P1 sources
•
Data cards and licence table
•
Canonical schema ADR
•
Adapters with unit tests
•
Validation suites wired into CI
•
Rebuilding canonical data from raw on a clean machine
reproduces identical hashes
•
All validation suites pass; EDA statistics match literature
•
Schema ADR reviewed by every teammate
Pitfalls to watch for
AMLworld currencies and payment formats (a naive sum across currencies is meaningless). Loading multi-gigabyte CSVs
into pandas and running out of memory. Timestamp formats and time zones differing by dataset.
PHASE 2
Graph construction, labels and
federated partitioning
Timeline: Weeks 3–4
Owners: Anvi (lead), Dishant, Divvya
(support)
Goal
Per-institution transaction graphs with trustworthy labels, leak-free features, chronological splits and a
documented partitioning scheme.
Why this matters
The partitioning decides whether your federated experiments mean anything. Done properly it also produces the
project’s most persuasive table: how many rings no single institution can see in full.
Step-by-step instructions
1
Fix the graph formulation (ADR). Accounts are nodes; transactions are directed, timestamped edges in a
multigraph. Add other node types (device, bank) only where the dataset has them. Keep a heterogeneous
variant for later.
2
Define three label levels. Edge: laundering flag. Account: positive if it sends or receives at least one
laundering transaction (document this derivation). Ring: one group per instance in the AMLworld patterns file
(its transactions give its accounts).
3
Generate ring negatives. Create candidate sub-graphs without laundering edges: time-windowed weakly
connected components within a size range chosen from EDA, matched to positive size distribution. At serving
time candidates come from a detector, so later also evaluate the ring head on detector-produced candidates
to catch train/serve skew.
4
Engineer edge and node features. Log-scaled amount, currency, payment format, time since the previous
transaction of the same source, rolling counts and sums over 1 hour, 24 hours and 7 days, running in/out
degree, in/out amount ratios, cyclic time of day. Every feature uses only past information.
5
Define chronological splits (ADR). For example 60/20/20 by time. Decide the rule for rings that straddle a
boundary (for example assign by first transaction and exclude straddlers from test ring metrics) and write it
down.
6
Partition AMLworld by bank. Build the account-to-bank map and per-bank volumes. Group banks into K=6
institutions by a deterministic procedure; also produce K=3 and K=8 variants. Produce a balanced variant and
a size-skewed variant.
7
Define each client’s local graph. Every transaction where the source or destination account belongs to the
client. The foreign endpoint becomes a stub node (hashed ID, no features beyond what the transaction itself
shows).
8
Produce the blind-spot table. Per client: nodes, edges, laundering ratio, ring count, cross-institution edge
share. Globally: the share of rings fully visible to one client versus split across two or more. This is a headline
result of the project.
9
Add Dirichlet partitions. For sources with no natural institutions (PaySim, IEEE-CIS), split by Dirichlet over
labels or segments with concentration 100 (mild), 1.0 (moderate), 0.1 (severe). Report a measured
heterogeneity number such as Jensen-Shannon divergence between client label distributions.

FraudMesh — Production-Grade Plan of Action
Page 13
10 Reserve a neutral validation slice. Hold back a slice (for example a set of banks or a time window) that no
client trains on. RAP-FedAvg uses it in Phase 6.
11 Export graph artefacts. PyG-ready tensors (edge index, edge attributes, timestamps, labels, split masks)
and CSVs for Neo4j import. Register as a DVC stage.
12 Sanity-check visually and numerically. Plot five true rings and five negatives, check degree and
component-size distributions, and add an assertion that no feature timestamp exceeds its edge time.
13 Commit a tiny fixture. About 5,000 edges, 3 clients, 2 planted rings. It powers unit tests, CI and demos.
Deliverables
Exit criteria (definition of done)
•
Per-client graph artefacts for K=3, 6, 8
•
Label derivation ADR and split ADR
•
Blind-spot table
•
Neutral validation slice
•
Fixture dataset in the repository
•
Leakage assertion passes on all graphs
•
Blind-spot table reviewed and plausible
•
Graphs rebuild from canonical data with one DVC command
Pitfalls to watch for
Hub accounts causing neighbourhood explosion (plan degree caps now). Negative rings that are trivially different from
positives, making the ring head look perfect. Stub nodes accidentally carrying information the local bank could not know.
PHASE 3
Centralised baselines and evaluation
harness
Timeline: Weeks 4–6
Owners: Anvi (harness), Dishant (GNN
baselines)
Goal
Honest numbers to beat, produced by a harness that every later model must plug into.
Why this matters
A custom model is only impressive if the baselines are strong and the evaluation is fair. A weak baseline or a leaky
split is the commonest way student projects overclaim.
Step-by-step instructions
1
Specify the harness (ADR). Inputs: predictions on test edges, accounts and rings. Outputs: a metrics JSON.
Primary metric PR-AUC; also minority-class F1 at a threshold tuned on validation only, ROC-AUC, precision and
recall at k (k equals analyst capacity, for example the top 0.1 percent), ring recall at top-k, time-to-detection,
and false alerts per 1,000 transactions.
2
Require statistical rigour. At least 5 seeds; report mean and standard deviation; bootstrap confidence
intervals on the test set; thresholds never chosen on test data.
3
Reproduce a published reference. Run IBM’s reference GNN baselines on HI-Small and LI-Small and
confirm your numbers are in the same range as the AMLworld paper. If yours is far lower, suspect your splits
or features before the model.
4
Build M1. LightGBM or XGBoost on edge features plus graph-derived features (degree, fan-in and fan-out
counts, cycle and scatter-gather indicators). Tune with a fixed Optuna budget on validation. This is a very
strong baseline; expect it to be hard to beat on HI-Small.
5
Build M2. GraphSAGE, GAT and GIN or PNA with edge features using PyG neighbour-sampling loaders for
edge classification. Handle imbalance with weighted cross-entropy or focal loss and balanced negative
sampling per batch (do not use SMOTE on graphs). Try directed message passing with separate in and out
directions, as discussed in the directed-multigraph GNN literature.
6
Build M4 baselines. LightGBM and an MLP on IEEE-CIS (time split on TransactionDT), BAF (split by month),
PaySim and ULB. Report PR-AUC; do not compare across datasets.
7
Build the three reference points from the report. Centralised pooled model (upper bound), local-only
per client (lower bound), and FedAvg with plain GAT (arrives in Phase 4).

FraudMesh — Production-Grade Plan of Action
Page 14
8
Define the cross-dataset protocol. Train on HI-Small, test on LI-Small (same generator, different
laundering rate) and on SAML-D through its adapter. Report degradation; this is your evidence that models
are not tied to one dataset.
9
Automate results tables. Every run writes metrics JSON and logs to MLflow; a script regenerates Markdown
and LaTeX tables from MLflow. No hand-copied numbers anywhere.
10 Do error analysis. Break results down by laundering pattern type, amount band and account activity level.
Record which patterns each model misses; this guides Phase 5.
Deliverables
Exit criteria (definition of done)
•
Harness with unit tests
•
M1, M2, M4 baselines with 5-seed results
•
Reference reproduction note
•
Cross-dataset results
•
Auto-generated results tables
•
Reference reproduction within a stated tolerance
•
Harness metrics verified against a hand-computed toy case
•
Every baseline has five seeds and confidence intervals
Pitfalls to watch for
Choosing the threshold on test data. A random split that leaks time. Reporting accuracy or ROC-AUC alone. Under-tuned
baselines that make the custom model look better.
PHASE 4
Plain federated pipeline (Flower,
FedAvg)
Timeline: Weeks 6–7
Owners: Divvya (lead), Pranav
(container review)
Goal
Federated training of the baseline GNN across simulated institutions, first in simulation and then in containers with
TLS, with correctness checks that prove it behaves like centralised training.
Why this matters
Add custom components only on top of a federated pipeline you trust. If plain FedAvg is wrong, every RAP-FedAvg
result is meaningless.
Step-by-step instructions
1
Fix the client contract (ADR). A client implements: return parameters, fit (local steps, proximal strength,
DP flag), evaluate (local metrics plus example counts). Only float tensors and scalar metrics cross the
boundary. Tag every parameter set with a model-config hash so mismatched architectures are rejected.
2
Start in simulation. Use Flower’s simulation engine with K=6 clients on the AMLworld partition and plain
FedAvg. Fix seeds, make client sampling deterministic, log per-round and per-client metrics to MLflow.
3
Prove correctness. With one client, FedAvg must equal centralised training. With an IID split and enough
rounds, the federated model should approach the centralised model. If not, debug now.
4
Handle GNN-specific issues. Normalise by local steps rather than epochs, so large clients do not drift
further. Use LayerNorm or GroupNorm instead of BatchNorm (BatchNorm statistics average poorly and
Opacus rejects it). Use shared, fixed feature scaling constants, or a one-off federated statistics round, rather
than per-client fitted scalers.
5
Evaluate in two ways. Client-side evaluation aggregated by weight, plus server-side evaluation on the
neutral validation slice. Use the server-side curve for early stopping.
6
Run the optional heterogeneous-schema experiment. A shared GNN trunk with per-client input
encoders that stay local and are not aggregated. Document that averaging mismatched input layers is
invalid.
7
Add fault tolerance. Minimum-clients thresholds, per-round timeouts, straggler cutoff, retries. Checkpoint
the global model every round and support resuming. Simulate a client crashing in round r.
8
Build the federated M4. Federate the tabular scorer within each dataset family: IEEE-CIS clients by
ProductCD, and BAF variants as clients. Use an MLP, or Flower’s tree-based strategy if you want boosted
trees.

FraudMesh — Production-Grade Plan of Action
Page 15
9
Move to deployment mode. Containerise server and clients and run them with Flower’s deployment
runtime (SuperLink and SuperNode) on a private Compose network. Enable TLS with a self-signed CA and
node authentication. Show that a client with the wrong certificate is rejected. Flower’s API changed across 1.x
releases, so follow the documentation for the version you pinned.
10 Add a data-leak guard. An automated test that inspects what a client sends and asserts it contains only
parameter arrays and metrics; log payload sizes per round.
11 Record communication cost. Bytes per round per client and total, for the final report.
Deliverables
Exit criteria (definition of done)
•
FedAvg in simulation and in containers
•
Correctness tests in CI on the fixture
•
Federated M4 results
•
Checkpoint and resume support
•
TLS-secured deployment compose file
•
K=1 equals centralised (CI test)
•
Simulation and containerised runs agree within a stated
tolerance
•
A client with an invalid certificate is rejected
•
A simulated client crash does not stop training
Pitfalls to watch for
Letting client identities leak into logged tensors. GPU non-determinism confusing comparisons (fix seeds and note
residual variance). Update size growing with model width.
PHASE 5
TW-TR-GAT
Timeline: Weeks 7–9
Owners: Dishant (lead), Divvya (DP
compatibility review)
Goal
A tested, ablatable implementation of the relational edge encoder, causal temporal-decay attention and
ring-aware readout, trained first centrally and then plugged into the federated loop.
Why this matters
This is the project’s model contribution. Building it as a ladder (each component added and measured separately)
gives you a working model at every step and produces the ablation study as a by-product.
Step-by-step instructions
1
Write a one-page specification (ADR). Tensor shapes, definitions of the edge, account and ring heads,
loss, hyperparameters, units and normalisation of the time difference, and how the layer is implemented in
PyG (a custom message-passing layer with an attention bias).
2
Build as a ladder. L0: plain GAT with edge-feature input that matches a trusted reference layer. L1: add the
relational edge encoder. L2: add temporal decay. L3: add the ring readout. At each rung write unit tests, run
training, and log the change against the previous rung.
3
Implement the edge encoder. A small network over log amount, channel embedding, direction flag and
normalised time features, injected into the attention logit as in the report, optionally also into the message
values. Keep a switch for the ablation.
4
Implement temporal decay in logit space. Subtract λ·Δt inside the logit before softmax, with λ =
softplus(parameter) per head so it stays positive, initialised near the median inter-transaction gap from EDA.
This keeps attention normalised and is equivalent to the report’s form up to renormalisation. State this in the
report.
5
Enforce causality. For a target at time t, attend only to edges with timestamp at most t. Use time-aware
neighbour sampling in PyG (check the documentation for the pinned version). Without this you leak the future
and your results are invalid.
6
Implement the ring readout. Mean pooling over a candidate sub-graph as specified; batch rings through a
batch-index vector. Run cheap variants as ablations (mean plus max, attention pooling). Train negatives at a
modest ratio but evaluate at the natural ratio.
7
Balance the multi-task loss. Edge or account cross-entropy plus β times ring cross-entropy. Monitor
gradient norms per head so one does not dominate, and tune β on validation.
8
Measure size and latency. Parameter count (this is your update size per round) and CPU latency per 2-hop
sub-graph. Set a target, for example under 200 ms for about 300 nodes, and record whether you meet it.

FraudMesh — Production-Grade Plan of Action
Page 16
9
Write the model tests. Shape tests; invariance to node ordering; older edges receive no more attention
than newer ones, all else equal; attention sums to 1 per target; gradients reach λ and the edge encoder; the
model can overfit a tiny batch; determinism with a fixed seed; the state dict round-trips through Flower’s
parameter serialisation.
10 Train centrally first. On pooled HI-Small, reach or beat M2 before going federated. Use a fixed, logged
hyperparameter budget on validation only.
11 Design the ablation study. Full model; without edge encoder; without temporal decay; without ring head;
plain GAT; GraphSAGE. Five seeds each, with change in PR-AUC and F1 with confidence intervals, repeated on
SAML-D to show effects are not dataset-specific.
12 Export interpretability hooks. Per-edge attention weights, learned λ per head, and an edge-importance
routine for Model M6, for the console.
Deliverables
Exit criteria (definition of done)
•
TW-TR-GAT package with ladder of tests
•
Centralised results versus M1 and M2
•
Ablation results on AMLworld and SAML-D
•
Checkpoint format: state dict plus config JSON
•
Latency and size report
•
Test suite green in CI
•
Either TW-TR-GAT beats plain GAT on validation by a stated
margin, or the negative result is documented honestly with
analysis
•
Federated loop runs with the new model on the fixture
Pitfalls to watch for
If temporal decay does not help, check timestamp resolution first (AMLworld timestamps are coarse; confirm in EDA) and
report the finding rather than tuning until it appears to work. Ring negatives that are too easy. Per-example memory
growth when sub-graphs are large.
PHASE 6
RAP-FedAvg
Timeline: Weeks 9–10
Owners: Divvya (lead)
Goal
A custom Flower aggregation strategy with reputation weighting, proximal regularisation and capped adaptive
client weights, benchmarked and stress-tested against poisoning.
Why this matters
Robust aggregation is the second research contribution. Its credibility depends on a precise specification, strong
tests, honest threat models and fair baselines.
Step-by-step instructions
1
Write the specification (ADR). Reputation update as an exponential moving average of each client’s
validation contribution; clip scores; a reputation floor so a client can recover; initial reputation 1. Capped
weights computed by iterative water-filling so the cap still holds after renormalisation. Proximal strength μ
with a tuning range.
2
Choose the contribution score. Leave-one-out gain on validation PR-AUC is cleanest but costs K+1
evaluations per round. A cheaper option is evaluating each client’s model alone against the global one. State
the trade-off and which you chose.
3
Implement as a Flower strategy. Send μ and the round number in the fit configuration; compute weights
in the aggregation step; persist reputation state to disk and MLflow each round so training can resume; log
weights per round (this feeds the dashboard).
4
Sanitise updates before aggregating. Reject NaN and Inf, clip update norms relative to the median norm,
and log every rejection.
5
Write strategy tests. Weights sum to 1; the cap holds; equal reputations with no cap reproduce FedAvg;
μ=0 reproduces the plain local objective; a NaN update is excluded; aggregation is invariant to client order.
6
Document the trust model (ADR). The server sees individual updates and holds a neutral validation slice,
so secure aggregation cannot be combined with per-client reputation. State this plainly. Possible extension, if
time allows: compute reputation from client-reported metrics under secure aggregation.

FraudMesh — Production-Grade Plan of Action
Page 17
7
Run the comparison set. FedAvg, FedProx (μ only), reputation only, cap only, full RAP-FedAvg (this also
serves as its ablation), and your FedFraud-style trust weighting. Identical seeds and rounds for all.
8
Study sensitivity. Small logged grids over EMA rate, μ, cap and floor; plot results rather than reporting a
single lucky setting.
9
Define poisoning threat models. Random-noise client; label-flip client; scaled-update (model replacement)
client; free-rider that returns the global model unchanged. Test 1 of 6 and 2 of 6 malicious clients. Measure
the drop in PR-AUC and the round at which the malicious client’s weight falls below a threshold.
10 Probe an adaptive attacker (stretch). A client that behaves well until its reputation is high and then
attacks. Report whether reputation weighting is fooled.
Deliverables
Exit criteria (definition of done)
•
RAP-FedAvg strategy and tests
•
Comparison results under mild, moderate and severe
heterogeneity
•
Poisoning results for four threat models
•
Trust-model ADR
•
All strategy tests pass in CI
•
RAP-FedAvg stable across seeds
•
Poisoned-client suppression measured in rounds, with
confidence intervals
Pitfalls to watch for
Leave-one-out evaluation cost blowing up round time. Reputation collapsing to zero for a small but honest client (hence
the floor and the cap). Comparing against a weakly tuned FedProx baseline.
PHASE 7
Differential privacy
Timeline: Weeks 10–11
Owners: Divvya (lead), Dishant
Goal
DP-SGD in local training with an explicit privacy claim, a persistent privacy ledger, a privacy-utility curve, and
empirical evidence that the noise reduces leakage.
Why this matters
A plotted epsilon curve means little unless the claim behind epsilon is stated correctly. On graphs that needs care,
and a careful treatment will stand out in the viva.
Step-by-step instructions
1
State the privacy claim (ADR). Define the privacy unit: one training example is one degree-capped,
sampled ego-sub-graph around a target edge or account. State clearly that the guarantee is with respect to
such examples and does not hide graph structure shared between examples. Choose δ below the reciprocal
of each client’s example count. Optionally add client-level DP (clip and noise whole updates) as a secondary
experiment, and keep the two claims separate.
2
Make the model Opacus-compatible. Run Opacus’s module validator and replace BatchNorm. Make sure
custom layers either use supported primitives (linear, embedding) inside, or write a custom per-sample
gradient routine. Define how the ring loss behaves per sample (one ring per example) or apply DP only to the
edge and account loss path and report that scope.
3
Build independent examples. Because message passing couples neighbours, precompute or generate
ego-sub-graphs with fixed caps so each example is self-contained. Use Poisson sampling over examples,
which the privacy accountant assumes. Expect higher memory use; prototype on the fixture before
committing.
4
Validate per-sample gradients. On a tiny batch, compare Opacus per-sample gradients against a loop that
computes gradients one example at a time. Silent mismatches with custom layers are the most dangerous
failure here.
5
Tune DP hyperparameters separately. Clipping norm (start near the median per-sample gradient norm),
noise multiplier, large logical batch size via virtual steps, learning rate, epochs. Do not reuse non-DP settings
and do not tune on test data.

FraudMesh — Production-Grade Plan of Action
Page 18
6
Account across rounds. Each round’s local DP-SGD adds privacy cost that composes. Use the RDP or PRV
accountant. Decide and document the allocation (fixed noise multiplier and report cumulative epsilon, or a
fixed total budget split over rounds). Stop a client when its budget is spent.
7
Build the privacy ledger. Append-only table of client, round, round epsilon, cumulative epsilon, delta, noise
multiplier, clip norm, sampling rate and steps. It feeds the consortium dashboard.
8
Run the sweep. Epsilon 1, 3, 8 and no-DP; five seeds; separately tuned settings per epsilon. Plot PR-AUC and
F1 versus epsilon with error bars, and report minority-class recall separately because DP hurts rare classes
most.
9
Check privacy empirically (stretch, high value). Run a membership-inference attack (loss-threshold or
shadow-model) against non-DP and DP models on a small set. Show attack AUC approaching 0.5 as epsilon
falls.
10 Test interplay with RAP-FedAvg. Noise makes validation-based reputation noisier. Measure it, and smooth
with a larger EMA window if needed.
Deliverables
Exit criteria (definition of done)
•
DP-enabled training with per-sample gradient validation
•
Privacy ledger table and service
•
Privacy-utility curve
•
Privacy-claim ADR
•
Membership-inference results (stretch)
•
Per-sample gradient check passes
•
Ledger totals match the accountant’s own epsilon
•
Curve reproduced with five seeds
Pitfalls to watch for
Reporting epsilon without delta, accountant and sampling rate. Computing epsilon with the wrong sampling rate. Using
the same hyperparameters for DP and non-DP and concluding DP “destroys” accuracy.
PHASE 8
Full experiment campaign and
statistical analysis
Timeline: Weeks 11–12
Owners: Anvi (lead), all
Goal
Every comparison promised in the report executed on frozen code and data, with statistics, reproducible
commands and auto-generated figures.
Why this matters
This phase is where the project’s claims either earn their place or get corrected. Freezing code and data first
prevents quiet changes that invalidate earlier runs.
Step-by-step instructions
1
Freeze. Tag the code, lock dataset versions in DVC, lock the container image. Any later change needs a new
tag and a rerun of affected experiments.
2
Build the experiment matrix as config sweeps. One config per cell of the table below, seeds as a sweep
dimension. Estimate the total GPU hours before launching and order runs by priority (E1, E2, E3 first).
3
Run on one image. Execute in the same container used in CI and log every run to MLflow with tags for
experiment ID and seed.
4
Analyse with statistics. Mean and standard deviation across five or more seeds; bootstrap confidence
intervals; paired comparison across seeds (bootstrap or Wilcoxon, noting low sample size). Report negative
results as they are.
5
Produce the headline figure. Ring recall for rings split across two or more institutions: local-only versus
federated versus centralised. This demonstrates the cross-institution blind spot directly.
6
Generate everything automatically. Tables and figures come from a script reading MLflow. Add
communication-cost and compute-time tables.
7
Write a reproducibility sheet. One page listing the exact configs and commands that regenerate each
table and figure.

FraudMesh — Production-Grade Plan of Action
Page 19
Deliverables
Exit criteria (definition of done)
•
Results database in MLflow
•
Auto-generated tables and figures
•
Reproducibility sheet
•
Every table in the report traces to logged runs
•
A teammate regenerates one figure from the sheet alone
Pitfalls to watch for
Quietly re-running only the cells that disappoint (decide the matrix in advance). Using different seeds for different
methods in the same comparison.
ID
Question
Conditions
Metrics
E1
Overall ring-detection quality
Centralised, local-only, FedAvg+GAT,
FedAvg+TW-TR-GAT, RAP-FedAvg+TW-TR-GAT
PR-AUC, F1, precision@k, ring
recall
E2
Contribution of each custom
GNN component
Full, minus edge encoder, minus decay, minus ring
head, GAT, GraphSAGE; on AMLworld and SAML-D
Change in PR-AUC and F1 with CIs
E3
Aggregation under non-IID
data
FedAvg, FedProx, FedFraud-style, RAP-FedAvg at
Dirichlet 100, 1.0, 0.1
Degradation mild to severe,
rounds to target
E4
Robustness to a poisoned
client
Four threat models, 1 of 6 and 2 of 6
PR-AUC drop, rounds to suppress
E5
Privacy-utility trade-off
Epsilon 1, 3, 8, no-DP
PR-AUC and F1 versus epsilon;
attack AUC (stretch)
E6
Cross-dataset generalisation
Train HI-Small; test LI-Small, SAML-D, Elliptic++
(node task)
Degradation versus in-domain
E7
Federated stage-1 scorer
IEEE-CIS clients by ProductCD; BAF variants as
clients
PR-AUC versus local-only and
pooled
E8
Two-stage pipeline
M4 filter then M3, with M5 calibration
Alerts per 1,000 transactions at
fixed recall, latency
PHASE 9
Model packaging, registry and serving
Timeline: Weeks 11–13
Owners: Pranav (lead), Dishant
Goal
A per-institution inference service that loads a registry-promoted model, scores transactions and candidate rings,
and explains its alerts, with defined latency targets.
Why this matters
Serving is where training and production usually diverge. Sharing one feature code path, gating promotions and
measuring latency are what separate a demo from a service.
Step-by-step instructions
1
Define the model artefact standard. State dict, config, feature specification, scaler constants, schema
version, training-data hash, validation metrics, git SHA, DP summary. Register in MLflow with stages:
candidate, staging, production.
2
Add promotion gates. A candidate moves to production only if it beats the current production model on
validation PR-AUC by a stated margin and passes latency and smoke tests. Rollback is one action: promote
the previous version.
3
Serve in eager PyTorch first. Exporting custom PyG message passing to TorchScript or ONNX is brittle. Use
inference mode, tuned threads and a batch endpoint. Note the alternative in the report.
4
Design the API contract-first. Versioned routes under /v1: score a transaction, score a ring, fetch an
account sub-graph with attention, model info, health, readiness, metrics. Define Pydantic schemas, publish
OpenAPI, and generate the console’s TypeScript client from it.
5
Assemble sub-graphs online. On a new transaction, write it to the graph store, fetch the causal 2-hop
neighbourhood within a time window, apply the same degree caps as training, build features through the
same shared package. Add a parity test comparing offline and online features on 1,000 transactions.

FraudMesh — Production-Grade Plan of Action
Page 20
6
Assemble candidate rings. On a high edge or account score, expand a connected component within the
window, score the ring, merge overlapping candidates, and raise an alert only above a per-institution
threshold set from validation to meet a target alert rate. Calibrate scores (isotonic or Platt) so they are
interpretable.
7
Set service-level targets. For example p95 under 300 ms per transaction on CPU and 50 transactions per
second per institution. Adjust to what you measure, then load-test with Locust or k6 and profile hot spots;
cache neighbourhoods.
8
Make it reliable. Request IDs, idempotent alert creation, timeouts, and graceful degradation: if the graph
store is down, fall back to the stage-1 score and mark the response as degraded.
9
Wire the two stages. M4 as a quick filter, M3 on items above a low threshold, M5 to calibrate and combine.
Keep the combiner simple.
10 Serve explanations (Model M6). Top edges by attention or importance, motif tags (cycle, fan-in, fan-out,
scatter-gather) from a graph pattern routine, plus reason codes such as velocity and amount anomaly.
Compute only for alerts.
11 Build a replay simulator. A service that feeds test-period transactions into each institution at a
configurable speed (a plain async queue is enough; Kafka or Redpanda is optional), plus a ring injector that
plants a synthetic mule ring across two or three institutions for the demo.
Deliverables
Exit criteria (definition of done)
•
Registry with gated promotion
•
Inference service with OpenAPI spec
•
Feature-parity test
•
Load-test report
•
Replay simulator and ring injector
•
p95 latency target met or deviation documented
•
Parity test passes
•
A deliberately worse model is blocked by the gate, and
rollback works
Pitfalls to watch for
Re-implementing features in the serving code instead of importing them. Unbounded neighbourhood expansion on hub
accounts. Thresholds picked on the test set.
PHASE 10
Data layer and feedback loop
Timeline: Weeks 12–13
Owners: Pranav (lead), Anvi
Goal
Per-institution Postgres and Neo4j stores, idempotent ingestion, and a label write-back loop that stays inside each
institution.
Why this matters
Case history, audit trails and labels are the system of record. Getting the schema and the feedback path right
early avoids painful migrations later.
Step-by-step instructions
1
Create one stack per institution. One Postgres and one Neo4j per institution. Neo4j Community Edition
supports a single user database, so use a container per institution. Template this in Compose.
2
Design the relational schema on paper first. Users, roles, institutions, alerts, rings, ring accounts, cases,
case events (append-only audit), labels, model versions, reports. Add constraints and indexes, scope rows by
institution, manage changes with Alembic migrations. Draw an ER diagram in docs.
3
Model the graph. Account nodes, transfer relationships carrying transaction ID, timestamp, amount and
channel; optional device nodes. Add uniqueness constraints on account ID and an index on timestamp.
Always bound queries by hop count, time window and LIMIT.
4
Build ingestion. Canonical Parquet to the graph store with idempotent upserts and batch loading. Load only
the as-of window you need; benchmark 2-hop query latency and record it.
5
Build the feedback loop. Closing a case writes a label (confirmed, false positive, needs evidence) with
analyst, time and note into that institution’s Postgres. A nightly job materialises a versioned training snapshot
with a label-delay field. Use confirmed and false-positive labels; exclude “needs evidence” until resolved.

FraudMesh — Production-Grade Plan of Action
Page 21
6
Counter selection bias. Randomly sample un-alerted transactions for review and include them in the
snapshot with provenance recorded.
7
Enforce data boundaries. The consortium database holds only model metadata, the privacy ledger and
aggregate metrics. Add a test asserting its schema contains no account or transaction columns, and that no
tenant container can reach another tenant’s database.
8
Add backup and seed tooling. Backup and restore scripts and a seed script that loads the fixture for
demos and tests.
Deliverables
Exit criteria (definition of done)
•
Tenant Postgres and Neo4j with migrations
•
Ingestion pipeline
•
Label write-back and snapshot job
•
Boundary tests
•
Ingestion is idempotent (running twice changes nothing)
•
2-hop query latency recorded
•
Boundary tests pass in CI
Pitfalls to watch for
Unbounded graph traversals. Treating Neo4j as the system of record for cases (use Postgres). Labels with no
provenance, which makes later audit impossible.
PHASE 11
FraudMesh web console
Timeline: Weeks 12–14
Owners: Pranav (lead)
Goal
A tenant-scoped, role-aware analyst console with five screens, built against the API contract and covered by
automated end-to-end tests.
Why this matters
Analysts judge the whole project by this interface. Designing for investigator workflows rather than for a demo is
what makes it credible.
Step-by-step instructions
1
Design before coding. Write three personas (investigator, compliance officer, administrator), map their
journeys, and sketch low-fidelity wireframes for the five screens. Review them with your guide or any person
with finance experience.
2
Choose the stack. React with TypeScript and Vite, Tailwind, TanStack Query for server state, React Router,
an accessible component kit. For the graph use Cytoscape.js with a force or hierarchical layout plugin: it
handles analysis-style layouts better than most force-graph libraries for a few hundred nodes.
3
Develop against a mock. Generate the API client from OpenAPI and run a mock server so UI work does not
wait for the backend.
4
Implement authentication and roles. OIDC or short-lived JWTs with refresh (Keycloak in Compose is the
heavier option). Roles: analyst, senior analyst or compliance, administrator, consortium viewer. Enforce
institution scoping on the backend, not only in the UI.
5
Build the Alert Queue. Server-side pagination, sorting and filters (institution, amount, time, status), saved
filters, ageing against a target response time, assignment.
6
Build the Graph Explorer. Ego expansion on click, a time slider that replays how the ring formed, edge
width by amount, colour by risk, tooltips with attention and recency, motif tags, a legend, a cap on rendered
nodes with an explicit expand control, PNG export, keyboard navigation.
7
Build the Case Workflow. A state machine from new, in review, confirmed, false positive or needs
evidence, to escalated and closed. Comments, evidence links, assignment, and a complete audit trail of every
transition.
8
Build the Model and Privacy Dashboard. Training rounds, per-institution reputation, epsilon ledger and
accuracy versus epsilon. It calls aggregate endpoints only.
9
Build Reports and Export. Server-side PDF and CSV per ring: account list, timeline, transactions, score,
analyst decision, model version, generated by and when, and a visible “synthetic data” marker. Confirm with
a domain person what a compliance hand-off needs; do not claim regulatory compliance.

FraudMesh — Production-Grade Plan of Action
Page 22
10 Handle every state. Loading, empty, error and session-expired states everywhere; optimistic updates for
case actions with rollback; virtualised tables; graphs of a few hundred nodes at smooth frame rates.
11 Make it usable. Keyboard shortcuts for analysts, a colour-blind-safe palette, adequate contrast.
12 Test it. Component tests (Vitest and Testing Library) and Playwright journeys: log in, open an alert, explore
the graph, confirm, export.
13 Secure it. Content-security-policy headers, no tokens in local storage (prefer HTTP-only cookies), CSRF
handling, escaping of all rendered text (account names and notes are untrusted), rate limiting.
Deliverables
Exit criteria (definition of done)
•
Five working screens against the real API
•
Role and tenant enforcement tests
•
Playwright journeys in CI
•
Wireframes and a short usability note
•
An analyst in institution A cannot read any data from
institution B, verified by test
•
Every screen has loading, empty and error states
•
Core journey passes end-to-end in CI
Pitfalls to watch for
Rendering thousands of nodes at once. Trusting the UI for access control. Building the dashboard against raw tables
instead of aggregate endpoints.
PHASE 12
Security, observability and reliability
hardening
Timeline: Weeks 14–15
Owners: Pranav (lead), all
Goal
A system you can operate: secured boundaries, visible health, monitored model quality, rehearsed failures and
written runbooks.
Why this matters
Operational maturity is the clearest signal that the project is more than a notebook with a front end.
Step-by-step instructions
1
Harden containers. Multi-stage Dockerfiles, non-root users, pinned base images, health checks, resource
limits, .dockerignore, image scanning with Trivy in CI.
2
Isolate networks. Separate Compose networks per institution plus a federation network; expose only the
gateway. Test that institution A’s containers cannot reach institution B’s database. Keep secrets in Docker
secrets or an untracked .env.
3
Secure the FL channel. Mutual TLS between nodes and server, node authentication, payload size limits.
4
Secure the APIs. Authentication on every route, role tests, input validation, request size limits, rate limiting,
error responses without stack traces. Run pip-audit and npm audit in CI, with secret scanning enabled.
5
Add observability. Structured JSON logs with correlation IDs, Prometheus metrics (latency, score
distribution, alert volume, FL round time, client contribution) and Grafana dashboards for service health,
model health, training and privacy budget, with alert rules for p95 latency, error rate, failed rounds and
epsilon nearing budget.
6
Monitor the model. Feature drift (PSI or KS) against training data, score distribution drift, alert-rate drift,
and performance once labels arrive. Write a retraining trigger policy. Demonstrate drift detection with a
replay over BAF months or later AMLworld windows.
7
Run failure drills. Kill a client mid-round, corrupt a checkpoint, stop a database, slow a graph query. Record
what happens and write a one-page runbook for each.
8
Define the release process. Semantic version tags, a changelog, a release checklist, versioned configs.
9
Write model and data documentation. A model card (intended use, data, metrics, limitations, failure
modes, DP statement, alert-rate comparison across institutions and channels) and the data cards from Phase
1.
10 Audit reproducibility. Ask someone outside the team to reproduce one result using the documentation
alone.

FraudMesh — Production-Grade Plan of Action
Page 23
Deliverables
Exit criteria (definition of done)
•
Hardened images and compose topology
•
Dashboards and alert rules
•
Drift monitor demo
•
Runbooks for four failure drills
•
Model card
•
Image scan has no unresolved critical findings
•
Each drill has a recorded outcome and runbook
•
An outsider reproduces a result from the docs
Pitfalls to watch for
Dashboards nobody checks (tie each to an alert). Treating DP and TLS as a substitute for access control. Skipping the
outsider reproduction test.
PHASE 13
Integration and acceptance demo
Timeline: Week 15
Owners: Pranav (lead), all
Goal
A scripted, automated end-to-end acceptance run in which a planted cross-institution mule ring is detected,
investigated, labelled and fed back into training.
Why this matters
The demonstration must not depend on luck. An automated scenario shows the system works as a system and
gives you a fallback when something fails on the day.
Step-by-step instructions
1
Write the acceptance scenario. Start the whole stack with one command. Run federated training for K=6
with shortened rounds (and a pre-trained checkpoint as fallback). Promote the model through the gate. Start
the replay.
2
Plant the ring. Inject a mule ring that moves funds through about five intermediate accounts within minutes
across two or three institutions. Verify an alert appears within the target time, and that the ring is correctly
linked across institutions only through the permitted channels.
3
Walk the analyst path. Open the alert, explore the graph, confirm the case, export the report. Verify the
label is written only to that institution’s database.
4
Close the loop. Show that the confirmed label enters the next training snapshot and that the next round
updates reputation and the privacy ledger.
5
Show the boundary. Open the consortium dashboard and demonstrate it contains aggregates only.
6
Automate it. Express the scenario as a pytest plus Playwright pipeline and run it in CI nightly.
7
Stress it. A one-hour soak test at replay speed, plus one failure drill performed live.
8
Prepare for demo day. Rehearse three times, record a backup video, and create an offline laptop mode
that runs from the fixture. Capture the final headline numbers in one slide.
Deliverables
Exit criteria (definition of done)
•
Automated acceptance pipeline
•
Soak-test report
•
Demo script, backup video, offline mode
•
Planted ring flagged within the target time on three
consecutive runs
•
Acceptance pipeline green on main
•
Demo rehearsed with no manual fixes
Pitfalls to watch for
A demo that needs a GPU on the day. Time-consuming model training inside the live demo. Relying on one laptop.

FraudMesh — Production-Grade Plan of Action
Page 24
PHASE 14
Documentation, report and viva
Timeline: Week 16
Owners: Anvi (lead), all
Goal
A final report whose every number traces to a logged run, a clean repository, and a team ready for hard
questions.
Why this matters
Clear writing and honest limits matter as much as the system, because the report is what remains after the demo.
Step-by-step instructions
1
Map the report structure. Introduction and scope, related work, data and graph construction, architecture,
TW-TR-GAT, RAP-FedAvg, differential privacy, evaluation, system and console, security and operations,
limitations, conclusion. Reuse ADRs as design-rationale text.
2
Pull results from the pipeline. Tables and figures come from the auto-generated outputs only. Cite
experiment IDs and seeds.
3
Write the limitations section carefully. Synthetic data does not transfer to real banks without validation;
ring definitions come from generators; simulated institutions share one generator; DP guarantee scope;
reputation trust model; no regulatory certification.
4
Write the ethics note. Synthetic data, no real personal data, misuse risks of fraud-detection tooling,
fairness checks performed and their limits.
5
Finish the repository. README with a quick start, architecture docs, ADR index, results reproduction guide,
licence and dataset attribution.
6
Prepare for the viva. Rehearse answers to questions such as: Why a GNN over gradient-boosted trees?
Where does your model beat M1 and where does it not? What does epsilon of 1 actually promise here? How
do you know reputation weighting cannot be gamed? What happens when institutions’ schemas differ? Why
not secure aggregation? How would this change with real data? What did you drop and why?
7
Freeze and archive. Tag the final release and archive the code, configs and result tables (a GitHub release
or Zenodo deposit).
Deliverables
Exit criteria (definition of done)
•
Final report, slides and poster
•
Release tag and archive
•
Viva question bank with agreed answers
•
Guide has reviewed a full draft at least one week before
submission
•
Every claim in the report maps to a run or an ADR
Pitfalls to watch for
Writing the report from memory instead of from the logged results. Hiding negative findings. Leaving unresolved TODOs
in the repository.

FraudMesh — Production-Grade Plan of Action
Page 25
8. Quality gates
These gates apply across phases. A gate marked CI blocks merging; the others are checked at phase exit.
Layer
What is tested
Tools
Gate
Data
Schemas, ranges, referential integrity, leakage
assertions, adapter correctness on samples
Pandera or Great Expectations,
pytest
CI
Metrics
harness
Metrics against hand-computed toy cases; threshold
selected on validation only
pytest
CI
Models
Shapes, order invariance, decay monotonicity,
attention normalisation, gradient flow, overfit-a-batch,
determinism
pytest, PyTorch
CI
Aggregation
Weights sum to 1, cap holds, equals FedAvg in the
degenerate case, NaN rejection, order invariance
pytest, property-based tests
CI
Federation
K=1 equals centralised; simulation versus container
agreement; client crash and resume
Flower simulation, Compose
CI (fixture) and
phase exit
Privacy
Per-sample gradient equivalence; ledger equals
accountant; payload leak guard
Opacus, pytest
CI and phase exit
Serving
API contract tests; offline-online feature parity;
latency targets; degradation behaviour
pytest, Locust or k6
CI and phase exit
Data stores
Idempotent ingestion; migrations apply and roll back;
boundary and isolation tests
pytest, Alembic, Compose
CI
Console
Component tests; end-to-end analyst journey; role
and tenant enforcement
Vitest, Playwright
CI
Security
Dependency audit, image scanning, secret scanning,
RBAC tests
pip-audit, npm audit, Trivy
CI
Operations
Failure drills with runbooks; backup and restore;
reproduction by an outsider
Manual with checklist
Phase 12 exit
Acceptance
Planted-ring scenario end to end
pytest, Playwright
Nightly CI and
Phase 13 exit

FraudMesh — Production-Grade Plan of Action
Page 26
9. Risk register and MVP cut line
Risk
Likelihood
Impact
Mitigation and trigger
PyG, CUDA, Opacus and
Flower version conflicts
High
Medium
Pin and record in Phase 0; never upgrade mid-project. Trigger: any
import error after week 2 means stop and fix.
Compute shortage (GPU
hours)
High
High
Develop on HI-Small and the fixture; reduce seeds to 3 for
expensive cells only after agreeing with the guide; skip AMLworld
Medium.
TW-TR-GAT does not beat
baselines
Medium
Medium
Report honestly with ablation analysis; M1 will be strong. The
contribution is then the federated, private, robust system and the
analysis.
DP drives accuracy to near
zero
Medium
Medium
Tune clip and batch size separately; show the curve at larger
epsilon; report scope of the guarantee.
Opacus incompatible with
custom layers or ring head
Medium
High
Prototype on the fixture in week 7; fall back to DP on the edge and
account path only and state the scope.
Cross-institution edges
break local graph learning
Medium
High
Stub-node design in Phase 2; compare against pooled model early;
stretch: hashed-ID linkage.
Reputation weighting
unstable
Medium
Medium
Floor, cap, EMA smoothing, sensitivity grid; keep FedProx as
fallback result.
Scope creep in the console
High
Medium
Freeze the screen list in week 12; build thin vertical slices; polish
last.
Integration surprises late
Medium
High
Replay simulator and ring injector from week 11; nightly
acceptance run from week 13.
Team bottleneck on one
person
Medium
High
Pair reviews, CODEOWNERS with two names per module, ADRs for
every decision.
MVP cut line
Tier
Contents
If behind, drop in this order
Must have
AMLworld pipeline and partitions; M1 and M2 baselines; federated FedAvg
and RAP-FedAvg with M3; DP sweep at three epsilons; one inference service;
console with Alert Queue, Graph Explorer and Case Workflow; planted-ring
demo; ablation and non-IID results
Never drop
Should have
SAML-D generalisation; poisoning with four threat models; model registry
gating; Model and Privacy Dashboard; reports export; drift monitor;
runbooks; TLS deployment
Drop in reverse order of this
list, starting with drift monitor
and runbooks
Stretch
Membership-inference check; adaptive attacker; heterogeneous-schema
trunk and encoders; Elliptic++ heterogeneous graph; private set
intersection linkage; Kafka replay; Keycloak; AMLworld Medium
Drop first
Appendix: tool and reference links
These are the official or canonical documentation sites for the tools named in the plan. Always follow the
documentation for the exact version you pin.
Tool
Documentation
Flower (federated learning)
https://flower.ai/docs/
PyTorch Geometric
https://pytorch-geometric.readthedocs.io/
Opacus (differential privacy)
https://opacus.ai/
MLflow (tracking and registry)
https://mlflow.org/docs/latest/
DVC (data versioning)
https://dvc.org/doc
Hydra (configuration)
https://hydra.cc/docs/intro/
Polars
https://docs.pola.rs/

FraudMesh — Production-Grade Plan of Action
Page 27
Tool
Documentation
Pandera (data validation)
https://pandera.readthedocs.io/
Neo4j
https://neo4j.com/docs/
FastAPI
https://fastapi.tiangolo.com/
Cytoscape.js
https://js.cytoscape.org/
Playwright
https://playwright.dev/
Locust (load testing)
https://locust.io/
Evidently (drift monitoring)
https://docs.evidentlyai.com/
Prometheus
https://prometheus.io/docs/
Grafana
https://grafana.com/docs/
How links were verified
While preparing this plan I opened and confirmed the IBM AMLworld Kaggle page reference, the AMLworld paper, and the
Elliptic++ repository. The other dataset links and the documentation URLs are standard addresses from memory and
were not individually opened, so check each on first use. If any has moved, search the dataset name on Kaggle or the
tool name on its official site; the plan does not depend on exact URLs.
