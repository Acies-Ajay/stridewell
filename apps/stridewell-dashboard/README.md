# Stridewell — redesigned business workspace

This update is based on the app.py, ui.py, YAML, dependencies and grants in your uploaded str.zip. It preserves the CEO scorecard, sales, inventory, stock-cover, quarantine and ERP reconciliation queries while redesigning the application shell.

## Deploy this update

1. Extract str.zip. Open the str folder inside it.
2. Back up your existing Databricks workspace source folder.
3. Replace app.py, ui.py, app.yaml and requirements.txt in that source folder. Copy .streamlit/config.toml too. These are ordinary files, not notebooks. Keep them together; app.py imports ui.py.
4. Keep the existing SQL warehouse resource named sql-warehouse with Can use permission. app.yaml retains catalog sw_dev_ajay. If your deployed catalog differs, preserve your environment-specific catalog value.
5. Verify grants for all SIX data objects listed below. Your uploaded grants already include ops.recon_exceptions. Run the supplied grant_access.sql only after replacing its placeholder with the app service principal's application/client ID.
6. Deploy from the folder directly containing app.py. If you upload the outer str folder, select that str folder as the source path, not its parent.
7. Open the app URL. Test Executive, Sales, Inventory, Stock Coverage, Data Quality and Reconciliation with real data. Test Dark mode and Explain data in the header. Open the sidebar for preferences.

No personal tokens or additional hosting services are needed. No data writes or pipeline execution are added.

## Navigation and controls

- Top navigation: Executive, Overview, Sales, Inventory, Stock Coverage, Data Quality, Reconciliation and Guide.
- Dark mode: switches the workspace, cards, charts, controls and HTML record tables. The preference lasts for the Streamlit session; it is not stored to a database.
- Explain data: displays or hides the plain-language insight panels.
- Sidebar preferences: Compact layout, Chart labels, Full currency values, Compare periods.
- Refresh: clears cached queries. It does not execute your data pipelines. The refresh timestamp is labelled UTC and is separate from business dates.
- Sales period presets anchor to the last business date available in the source, not the current calendar day.
- Blank channel/location filters mean all values. Page filters do not silently carry over into unrelated modules.
- Stockout priority: puts the two existing stockout categories first in the status selector without changing their definitions.
- Record explorers: case-insensitive literal search, pages of 25 records, filtered CSV downloads. Downloads cover the matching loaded view, not an unlimited source-table export.

## Business requirements covered

| Business question | Page | Coverage | Source |
|---|---|---|---|
| How is the business performing? | Executive | Revenue, net units, derived ratios, preceding-period deltas, channel and location performance | gold.daily_sales |
| What drives the sales totals? | Overview / Sales | Date presets, custom dates, channel/location filters, trends and rankings | gold.daily_sales |
| Where is our stock? | Inventory | Single-date on-hand, reserved and inbound balances | gold.daily_inventory |
| Which stock needs review? | Stock Coverage | Existing statuses and a store/SKU preview | gold.stock_cover |
| Why did records fail validation? | Data Quality | Retained reason counts for POS and e-commerce | silver.quarantine_pos_sales; silver.quarantine_ecom_events |
| Where do financial amounts differ? | Reconciliation | Retained exception types, counts and summed absolute differences | ops.recon_exceptions |
| What does each page mean? | Guide | Business-question mapping, direct navigation, definitions and known gaps | Static app guide |

The original comprehensive case-study specification was not included in the upload. This map covers the uploaded application's capabilities, not an assertion that all original requirements are complete. Replenishment approval/write-back, order-level KPIs, product/category sales analysis, ageing and sell-through are not implemented here. The Guide explicitly identifies these gaps.

## Data access

The service principal needs USE CATALOG on sw_dev_ajay; USE SCHEMA on gold, silver and ops; and SELECT on:

- gold.daily_sales
- gold.daily_inventory
- gold.stock_cover
- silver.quarantine_pos_sales
- silver.quarantine_ecom_events
- ops.recon_exceptions

The ops table and difference_inr/exception_type columns are taken from your uploaded code, not independently verified against a live schema. Permission, warehouse and source failures are shown as unavailable, never as zero risk or a passing reconciliation.

## Metric definitions and interpretation

- INR formatting is preserved from your uploaded version. Use Full currency values to expand lakh/crore abbreviations.
- Net revenue = sum(net_sales_excl_gst). Gross revenue = sum(gross_sales_amt). Net units = sum(net_units).
- Net revenue per net unit = net revenue / net units. This is not transaction-level average selling price.
- Net/gross, returns/gross and discount/gross are source-value ratios. Their source amounts may have different tax bases; they must not be presented as a fully tax-normalised retention or returns metric without validating your pipeline definitions.
- Revenue per identified location uses every non-null store_code. It is not described as a physical-store-only metric because online locations may have a code.
- Growth compares the immediately preceding equal-length period when earlier history exists and the baseline is positive. Compare periods can disable it. Missing comparisons are not zero growth.
- Date bounds establish available history, not proof that every daily delivery arrived. Incomplete deliveries can still affect comparisons.
- The rolling mean uses observed values within 7 calendar days; missing dates are not silently filled with zero.
- Inventory uses one snapshot. Reserved is included in on hand. Inbound is separate; do not stack these three values as additive stock.
- Stockout categories come from the existing pipeline. No new risk thresholds are invented. Detail preview is limited to 500 records.
- Quarantine counts include retained history. They are not today's failures or a failure rate.
- Reconciliation counts exception records, not assumed unique store-days. An empty exception table alone cannot prove checks ran or passed. Absolute differences may contain overlapping exceptions, depending on the upstream schema.
- Executive sales loads are capped at 20,000 grouped rows; other sales views at 10,000. If exceeded, the app refuses to display truncated totals.
- Cached results live for up to five minutes.

## Validation and practical limits

Local checks: Python syntax; eight views in light and dark mode with Streamlit AppTest; preference toggles, literal record search, signed sales and empty sales. Test fixtures are temporary and are NOT included in this deployment.

Live warehouse queries, permissions, actual data values and Databricks deployment are not testable from this workspace. Browser screenshot validation was blocked by the runtime's browser-launch restrictions, so final pixel-level appearance should be checked after deployment, particularly on narrow screens. The interface includes responsive layout rules and theme-aware Plotly figures.

Custom CSS targets Streamlit's UI structure. Dependencies allow Streamlit 1.50 through the 1.x series; a future Streamlit DOM change may require CSS adjustments. The custom theme toggle does not change the operating system or native browser theme.

App service-principal authorization is preserved: users share the principal's data access. Individual user/store restrictions are not added by this redesign.
