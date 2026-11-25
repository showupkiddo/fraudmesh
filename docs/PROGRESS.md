# FraudMesh progress log

## Phase 0 status

- Status: complete
- Current milestone: repository skeleton, Python packaging, CI workflow, MLflow tracking, DVC-ready structure, and initial ADR set are in place.
- Outcome: the Phase 0 gate report was produced and the project is ready to begin Phase 1.

## Phase 1 status

- Status: complete. The fixture, AMLworld HI/LI, SAML-D, PaySim, BAF, ULB, and labeled IEEE-CIS train outputs have been rebuilt and independently checked.
- Current milestone: canonical `amount_inr` schema, Pandera validation, keyed pseudonymisation, source adapters, data cards, rate provenance, fixture and graph-source DVC stages, and streaming tabular converters for PaySim/BAF/ULB/IEEE-CIS are in place.
- Kaggle CLI issue: Kaggle 2.2.5 was installed for Python 3.13, but its per-user `Scripts` directory was absent from `PATH`. Invoking `kaggle.exe` by full path reports the version and authenticated dataset file listings work. The PowerShell fix is documented in `docs/DATA_SETUP.md`.
- Local DVC issue: the editable `fraudmesh` install pointed at an old checkout under the user's Desktop, so `dvc repro` could not import this repository. Reinstalling `.[dev,data]` from this checkout fixed it; the fixture stage rebuilt 15 rows with the same SHA-256 recorded below.
- Downloads: AMLworld, PaySim, SAML-D, BAF, ULB, and IEEE-CIS source files are present locally and were scanned. AMLworld and PaySim pre-existed; exact download dates for the other sources are not recorded. Current Kaggle metadata reports the licences recorded in `data/cards/catalog.json`.
- Observed raw-source scans: AMLworld HI-Small has 5,078,345 rows and 11 columns (5,177 laundering-labelled rows); LI-Small has 6,924,049 rows and 11 columns (3,565 laundering-labelled rows). PaySim has 6,362,620 rows and 11 columns (8,213 fraud-labelled rows). These are file scans, not model results.
- Additional full raw scans: SAML-D has 9,504,852 rows and 12 columns (9,873 laundering-labelled rows, no blank cells); each of six BAF variants has 1,000,000 rows (32 or 34 columns; month indices 0–7); ULB has 284,807 rows and 31 columns (492 positives, no blank cells). Published summary checks are recorded below; BAF's extra columns in Variants III/V still need explanation against the datasheet.
- IEEE-CIS scan: 590,540 training transactions (20,663 positives), 506,691 unlabeled test transactions, 144,233 train identity rows, and 141,907 test identity rows. Transaction IDs are unique in all four files; every identity row joins to a transaction, and no transaction rows are duplicated.
- Published-summary checks: AMLworld HI/LI row counts and positive-label rates align with the dataset page's rounded 5M/7M and 1-in-981/1-in-1,942 figures; SAML-D's 9,873 positives equal the published 0.1039% after rounding; ULB's 492/284,807 equals the published 0.172% after rounding; and all six BAF files match the published 1,000,000 rows each. BAF Variants III/V include undocumented `x1`/`x2` columns beyond the stated 30 features, month, and target; the tabular pipeline excludes those columns pending source clarification.
- AMLworld pattern validation: every official pattern transaction matched exactly one row in the corresponding Small transaction file (HI-Small 3,209/3,209; LI-Small 1,023/1,023), with no duplicate matches or unmatched patterns. Positive-edge counts remain distinct from pattern-transaction counts.
- AMLworld HI-Small full DVC output verified: 5,078,345 rows, 5,177 positive edges, 3,209 ring-labelled rows, no nulls in required monetary/label/time fields, UTC timestamps, and `amount_inr: double`. The full Parquet hash is `392eb0bc6a0996f3637e7a0f8749cd8e839dc22011f082771e72a0cbe1e0b632`.
- BAF sample validation: the first 1,000 rows of Base and Variants I–V passed the current tabular adapter and schema checks. Their `month` values are relative indices; the sample check used an epoch solely to preserve ordering, not to assert real calendar dates.
- Tabular conversion sample validation: end-to-end temporary Parquet builds for the first 1,000 rows of each BAF variant, PaySim, and ULB passed schema, leakage, timestamp, and entity-pseudonym checks. BAF outputs have 30 features each; undocumented `x1`/`x2` are excluded from Variants III/V. Sample positive counts were Base 8, I 14, II 14, III 9, IV 7, V 13; PaySim 9; ULB 2.
- IEEE-CIS sample validation: the first 1,000 labeled training rows joined against the identity table, passed schema/leakage checks, and emitted fixed-shape pseudonymized card/device keys. Missing entity values use row-specific keyed placeholders, so they cannot create false cross-row links.
- INR policy: canonical monetary output is `amount_inr`. Fiat rates for 2022 and 2023 use cited annual ECB reference rates or World Bank WDI official annual averages, with cross-rate calculations documented in `docs/DATA_SETUP.md`. The 2022 BTC rate uses 18 Coinbase daily closes spanning the observed AMLworld period (September 1–18), cross-converted using the 2022 World Bank INR/USD average. These are annual/period averages, not transaction-date spot prices.
- Currency coverage: full AMLworld HI/LI source scans found 15 currency labels, all mapped to ISO codes and covered by the INR table for their 2022 source year. SAML-D's 9,504,852-row scan found 13 payment currencies and dates from 2022-10-07 through 2023-08-23; annual rates cover both years.
- SAML-D `Dirham` mapping: user confirmed AED; the year-specific INR conversion remains documented as an annual-rate approximation.
- AMLworld time coverage: HI-Small spans 2022-09-01 00:00 through 2022-09-18 16:18 UTC; LI-Small spans 2022-09-01 00:00 through 2022-09-17 15:28 UTC. The rate table loaded and covered every currency/year observed in the full transaction scans.
- Synthetic/unspecified units: PaySim simulation-unit amounts, ULB's unspecified `Amount`, and IEEE-CIS `TransactionAmt` are not presented as INR monetary outputs. PaySim is tabular-only; ULB remains a standalone tabular benchmark.
- SHA-256 of uncompressed source CSV members: HI-Small `b19d39f515523373f991b689c07e11e7b0b95c17a2c27a87d91584ae16c5b040`; LI-Small `f7a9940339c78b5d1476071505b5867c0f5319640b9c4279d13f531bf965319d`; PaySim `16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b`.
- IEEE-CIS raw CSV SHA-256: train transaction `3a5c83ab6b3cc13dcabe5ffa9f522307fd5f7f7b6e6f6a60c32284ca6283d642`; train identity `b63c725d8377be90a995268d97f347c17d456b95db45807adcf9f59cd603c37c`; test transaction `2a8e51f1d335a86025d2b7f45beb9b78d0ab1edd726ef531d8b71a8a0065c011`; test identity `3e5978cb13ca5e72f52babc4349ae0125e14b87ca8bfabe952ab67bb4ff1e10b`.
- Source archive SHA-256: SAML-D `87476ada943fc698ab30bc9ee132c68324ae762e4f9addb61d5347af3a738a00`; BAF `fb8d6d8b96f9a3c670a9ad0014da25ee8bee3fcb2be67bdcd115784bdb37cf8a`; ULB `a0360ce715992212e9ac72d8ccdca97f4be87dc1fdf2bed011358f7ab409a28a`.
- Main focus: complete available P1 tabular canonicalization, full-data validation, leakage review, EDA/literature comparison, and DVC rebuild evidence; configure the required team DVC remote.

## Decisions taken

- Selected one monorepo with clearly separated runtime modules for data, graph, models, federated, privacy, serving, console, infra, experiments, docs, and tests.
- Set the compatibility baseline in `COMPATIBILITY.md` and kept the environment locked for the current development runtime.
- Chose a CPU-first fixture workflow for local development and a GPU-capable path only when real compute is explicitly available.
- Established a local MLflow tracking pattern using `mlruns/` and a Dockerised MLflow server for the project.
- Adopted a canonical transaction schema in the `fraudmesh.data` package so downstream adapters and graph builders can share one contract.
- Added Pandera validation, explicit UTC normalization, reviewed-rate-table requirements, HMAC account pseudonymisation, leakage checks, and partitioned Parquet writers.
- Added row adapters for AMLworld, PaySim, IEEE-CIS, BAF, ULB, and a column-map-driven SAML-D adapter; the user confirmed SAML-D's `Dirham` currency label maps to AED.
- Initialized DVC locally and verified the fixture canonicalization stage; the project DVC remote is not configured.
- The fixture DVC stage emitted 15 canonical rows with SHA-256 `ec52bf3eba4f7830a12a0013d4c653e7cb072b94527d61378100cd6fc356cbcc`; this is fixture evidence only, not a real-dataset result.

## Phase 1 verified totals

- SAML-D: 9,504,852 rows, 9,873 laundering labels, full DVC output hash `bcfccca4c3e304a4c805c39aac0f0ca45da991f684a550fdd1a36e3958efd84a`.
- PaySim: 6,362,620 rows, 8,213 fraud labels.
- BAF: 1,000,000 rows per variant across Base and Variants I-V.
- ULB: 284,807 rows, 492 positive labels.
- IEEE-CIS labeled train: 590,540 rows, 20,663 positive labels.
- AMLworld HI-Small: 5,078,345 rows, 5,177 positive edges.
- AMLworld LI-Small: 6,924,049 rows, 3,565 positive edges.

## Phase 2 status

- Status: started.
- Added a DVC stage for AMLworld HI-Small graph artefacts.
- Initial run produced a six-institution partition covering 30,528 institutions, 5,078,345 edges, 6,357 positive accounts, and a ring count of 370.
- Chronological split counts: 3,047,007 train, 1,015,669 validation, 1,015,669 test.
- Next: expand client-local edge artefacts, ring negatives, split masks, and visual/quantitative graph sanity checks.

## Remaining project blockers

- A team-controlled DVC remote remains an operational requirement but is not needed for the local BTech implementation.
- Clean-machine rebuild evidence is not yet complete because no team remote is configured.
- Licence review remains pending where Kaggle metadata is not a legal determination.
- Full Phase 2 graph negatives and leakage checks remain to be implemented.

## Compute used

- Local CPU environment; 21 Phase 1 tests and the initial Phase 2 graph tests pass, Ruff and mypy pass.
- No GPU workload launched yet.
