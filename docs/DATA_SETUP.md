# Phase 1 data setup

## Dataset handling

Raw data belongs under `data/raw/<dataset>` and must not be committed to Git. Review each provider's licence and access terms before downloading or using a dataset. The dataset-card catalog records unknown counts and licences as pending rather than inventing them.

## Kaggle CLI in Windows PowerShell

On Windows, `pip` can install the package while placing `kaggle.exe` in the per-user Scripts directory, which may not be on `PATH`. Locate it and make it available in the current terminal:

```powershell
python -m pip show kaggle
$kaggleScripts = python -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))"
if (-not (Test-Path (Join-Path $kaggleScripts "kaggle.exe"))) {
    throw "kaggle.exe was not found for this Python interpreter"
}
$env:PATH = "$kaggleScripts;$env:PATH"
kaggle --version
```

For future VS Code terminals, add that directory to the Windows user `Path` and restart VS Code:

```powershell
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($userPath -split ";") -notcontains $kaggleScripts) {
    $newUserPath = (@($userPath, $kaggleScripts) | Where-Object { $_ }) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
}
```

Use the `kaggle` console command, not `python -m kaggle`. Test authentication with a metadata-only request:

```powershell
kaggle datasets files ealtman2019/ibm-transactions-for-anti-money-laundering-aml
```

Dataset downloads used for Phase 1:

```powershell
kaggle datasets download -d berkanoztas/synthetic-transaction-monitoring-dataset-aml -p data/raw/samld
kaggle datasets download -d sgpjesus/bank-account-fraud-dataset-neurips-2022 -p data/raw/baf
kaggle datasets download -d mlg-ulb/creditcardfraud -p data/raw/ulb
kaggle competitions download -c ieee-fraud-detection -p data/raw/ieee-cis
```

The IEEE-CIS file listing can succeed while its download is denied. If `competitions download` returns 403, open the competition rules while signed in to the same Kaggle account used by the CLI and confirm access there. Do not accept terms through automation.

The DVC pipeline contains a fixture stage and full-data conversion stages for AMLworld HI-Small, AMLworld LI-Small, SAML-D, PaySim, all six BAF variants, ULB, and the labeled IEEE-CIS training split. The unlabeled IEEE-CIS test split is deliberately excluded:

```powershell
python -m dvc repro phase1-fixture-canonical
python -m dvc repro
```

The real-data stages require the raw files, reviewed rates, and the same securely provisioned pseudonymization key on every rebuild. Each adapter must be tested against a source sample before it is used on the complete dataset. AMLworld conversion uses `Amount Paid` / `Payment Currency`; SAML-D uses `Amount` / `Payment_currency`. Ring membership must be loaded from the official AMLworld pattern files; it must not be inferred by graph propagation.

## INR output policy

The SAML-D source label `Dirham` is mapped to AED, as confirmed by the user. Annual-rate conversions are still approximations, not transaction-date spot rates.

The canonical monetary field is `amount_inr`. The source amount and its currency code are retained only for traceability; they must not be presented or aggregated as INR. `CurrencyRateTable` rejects non-INR base currencies and requires a year for annual-only rates. Unknown or missing source currencies fail conversion.

`data/config/currency-rates.csv` contains the reviewed rates for source years 2022 and 2023. Fiat rates use the World Bank indicator [PA.NUS.FCRF](https://api.worldbank.org/v2/indicator/PA.NUS.FCRF?format=json), which reports annual local-currency units per US dollar, and ECB annual reference rates from the [ECB exchange-rate API](https://data-api.ecb.europa.eu/service/data/EXR/A.INR.EUR.SP00.A?startPeriod=2022&endPeriod=2023&format=csvdata). Cross-rates are computed as INR per USD divided by source-currency units per USD, or as INR per EUR divided by source-currency units per EUR. The World Bank Data Catalog states its default open-data licence is [CC BY 4.0](https://datacatalog.worldbank.org/public-licenses). ECB information is freely reusable with source attribution, and calculated cross-rates are identified as modified, as required by the [ECB disclaimer and copyright terms](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html).

AMLworld Small records span 2022-09-01 through 2022-09-18. Its BTC INR rate uses the mean of the 18 available daily BTC-USD closing candles in that source range from the [Coinbase Exchange historical candles endpoint](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles), multiplied by the 2022 World Bank INR-per-USD annual average. The published table therefore uses period averages, not transaction-date spot rates; report that limitation anywhere the converted values are interpreted.

PaySim amounts are generator simulation units, and ULB's `Amount` source currency is not established by its card. They remain source features for the tabular benchmark and must not be labelled or reported as INR-denominated amounts. IEEE-CIS transaction-amount currency also requires source verification before any INR monetary output is produced.

The local HMAC key is stored outside Git at `%LOCALAPPDATA%\FraudMesh\pseudonymization.key`. Load it into each conversion terminal without printing it:

```powershell
$keyPath = Join-Path $env:LOCALAPPDATA "FraudMesh\pseudonymization.key"
$env:FRAUDMESH_PSEUDONYMIZATION_KEY = (Get-Content -Raw $keyPath).Trim()
```

Keep the key backed up in an approved secret store and share it with collaborators only through that store. Rebuilds must use the same key; a different key changes all pseudonyms.

`data/config/ring-labels.csv` is an optional manual-label input. AMLworld ring labels are read directly from the official patterns files during conversion.

## Configure a team-controlled DVC remote

Choose a team-owned storage location first. Then configure it without committing credentials:

```powershell
python -m dvc remote add -d storage <team-controlled-remote-url>
python -m dvc remote list
```

For remotes requiring credentials, use the provider's supported environment-variable or local secret-store mechanism. Do not put access keys in `.dvc/config`, Git, or chat. Do not upload restricted dataset contents to a remote until the dataset licence permits it.

## Dataset acquisition status

See `data/cards/catalog.json`. Kaggle metadata currently reports Community Data License Agreement - Sharing - Version 1.0 for AMLworld, CC BY-SA 4.0 for PaySim, CC-BY-NC-SA-4.0 for SAML-D and BAF, and "Database: Open Database; Contents: Database Contents" for ULB. These metadata values are not a legal review: confirm the applicable terms for the intended use before sharing raw or processed data. Download dates remain pending for AMLworld and PaySim because the original download dates were not recorded.
