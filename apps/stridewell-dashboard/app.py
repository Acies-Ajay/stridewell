import logging
import os
import re
import time
from datetime import timedelta, datetime, timezone
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
from ui import style, hero, insight, plot, bars, details, COLORS, inr, context
import streamlit as st
from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

st.set_page_config(page_title="Stridewell", page_icon="📊", layout="wide")
CATALOG = os.getenv("STRIDEWELL_CATALOG", "sw_dev_ajay")
WAREHOUSE = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
GENIE_SPACE_ID = os.getenv("GENIE_SPACE_ID", "")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", CATALOG):
    st.error("Invalid catalog configuration.")
    st.stop()


@st.cache_data(ttl=300, max_entries=64, show_spinner=False)
def query(statement, parameters=None, *, source):
    bound_parameters = dict(parameters or {})
    bound_parameters["source_table"] = source
    cfg = Config()
    with sql.connect(
        server_hostname=urlparse(cfg.host).hostname,
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE}",
        credentials_provider=lambda: cfg.authenticate,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(statement, parameters=bound_parameters)
            rows = cursor.fetchall()
            frame = pd.DataFrame.from_records(
                [tuple(row) for row in rows],
                columns=[column[0] for column in cursor.description],
            )
    # Convert SQL decimals to chart-friendly numbers without changing date/text columns.
    for column in frame.columns:
        if column.endswith(("_amt", "_gst", "_qty", "_units", "_count", "_cover", "_inr", "_pct")):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def table(schema, name):
    allowed = {
        ("gold", "daily_sales"), ("gold", "daily_inventory"), ("gold", "stock_cover"),
        ("silver", "quarantine_pos_sales"), ("silver", "quarantine_ecom_events"),
        ("ops", "recon_exceptions"),
    }
    if (schema, name) not in allowed:
        raise ValueError("Source table is not allowed")
    return ".".join((CATALOG, schema, name))


@st.cache_resource
def genie_client():
    return WorkspaceClient(config=Config())


def _id_of(obj, *names):
    for name in names:
        value = getattr(obj, name, None)
        if value:
            return value
    return None


def _message_text(message):
    text = getattr(message, "text_content", None)
    if text:
        return text
    parts = [chunk.text for chunk in (getattr(message, "content", None) or [])
             if getattr(chunk, "text", None)]
    return "\n".join(parts)


def _status_of(message):
    status = getattr(message, "status", None)
    return getattr(status, "value", status)


def ask_genie(question):
    """Ask the Stridewell Genie agent. Returns (answer_text, sql_text)."""
    genie = genie_client().genie
    started = genie.start_conversation(GENIE_SPACE_ID, content=question)
    conversation = getattr(started, "conversation", None) or started
    conversation_id = _id_of(conversation, "conversation_id", "id")
    message = getattr(started, "message", None)
    if message is None:
        message = genie.create_message(GENIE_SPACE_ID, conversation_id, content=question)
    message_id = _id_of(message, "message_id", "id")
    for _ in range(60):
        message = genie.get_message(GENIE_SPACE_ID, conversation_id, message_id)
        status = _status_of(message)
        if status and status != "PENDING":
            break
        time.sleep(2)
    status = _status_of(message)
    if status == "FAILED":
        return "The assistant could not answer that question. Try rephrasing it.", None
    if status != "COMPLETED":
        return "The assistant did not finish in time. Please ask again.", None
    sql_text = None
    for attachment in (getattr(message, "attachments", None) or []):
        if getattr(attachment, "query", None) is None:
            continue
        try:
            result = genie.get_message_attachment_query_result(
                GENIE_SPACE_ID, conversation_id, message_id, _id_of(attachment, "attachment_id", "id"))
            query = getattr(result, "query", None)
            for field in ("query_text", "query", "statement", "text"):
                candidate = getattr(query, field, None)
                if isinstance(candidate, str) and candidate.strip():
                    sql_text = candidate
                    break
            if sql_text:
                break
        except Exception:
            logging.warning("Genie query result fetch failed", exc_info=True)
    return _message_text(message) or "No answer was returned for that question.", sql_text


def executive():
    source = table("gold", "daily_sales")
    cover = table("gold", "stock_cover")
    ledger = table("ops", "recon_exceptions")
    bounds = query('SELECT MIN(business_date) first_date, MAX(business_date) last_date FROM IDENTIFIER(:source_table)', source=source).iloc[0]
    if pd.isna(bounds.first_date):
        st.info("No sales records are available yet.")
        return
    window = st.selectbox("Reporting window",
                          ["Last 7 days", "Last 30 days", "Last 90 days", "Last 180 days", "Full history"], index=1)
    end = bounds.last_date
    if window == "Full history":
        start = bounds.first_date
    else:
        start = max(bounds.first_date, end - timedelta(days=int(window.split()[1]) - 1))
    span = (end - start).days + 1
    prior_end = start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=span - 1)
    has_prior = prior_start >= bounds.first_date and st.session_state.get("compare_periods", True)
    frame = query("SELECT business_date, channel,\n        COALESCE(store_code, '(Unassigned)') store_code,\n        SUM(net_units) net_units, SUM(gross_sales_amt) gross_sales_amt,\n        SUM(sales_discount_amt) sales_discount_amt, SUM(returns_excl_gst) returns_excl_gst,\n        SUM(net_sales_excl_gst) net_sales_excl_gst\n        FROM IDENTIFIER(:source_table) WHERE business_date >= :prior_start AND business_date <= :end\n        GROUP BY business_date, channel, COALESCE(store_code, '(Unassigned)')\n        ORDER BY business_date LIMIT 20001", {'prior_start': prior_start, 'end': end}, source=source)
    if len(frame) > 20000:
        st.warning("This selection is too large for the executive summary. Choose a shorter window.")
        return
    frame["channel"] = frame["channel"].fillna("(Unassigned)")
    current = frame[frame.business_date.between(start, end)]
    prior = frame[frame.business_date.between(prior_start, prior_end)] if has_prior else frame.iloc[0:0]
    if current.empty:
        st.info("No sales records are available for this window.")
        return

    def total(rows, column):
        return rows[column].sum() if not rows.empty else 0

    def pct(now, then):
        return (now - then) / then * 100 if then > 0 and pd.notna(now) else None

    net_now = total(current, "net_sales_excl_gst")
    net_prior = total(prior, "net_sales_excl_gst")
    gross_now = total(current, "gross_sales_amt")
    gross_prior = total(prior, "gross_sales_amt")
    returns_now = total(current, "returns_excl_gst")
    returns_prior = total(prior, "returns_excl_gst")
    discount_now = total(current, "sales_discount_amt")
    units_now = total(current, "net_units")
    units_prior = total(prior, "net_units")
    net_growth = pct(net_now, net_prior)
    gross_growth = pct(gross_now, gross_prior)
    units_growth = pct(units_now, units_prior)
    returns_rate = returns_now / gross_now * 100 if gross_now else float("nan")
    returns_prior_rate = returns_prior / gross_prior * 100 if gross_prior else 0.0
    returns_growth = pct(returns_rate, returns_prior_rate) if gross_prior else None
    discount_rate = discount_now / gross_now * 100 if gross_now else float("nan")
    selling_days = current.business_date.nunique()
    active_stores = current.loc[current.store_code != "(Unassigned)", "store_code"].nunique()
    discount_prior = total(prior, "sales_discount_amt")
    discount_prior_rate = discount_prior / gross_prior * 100 if gross_prior else 0.0
    discount_growth = pct(discount_rate, discount_prior_rate) if gross_prior else None
    realization_rate = net_now / gross_now * 100 if gross_now else float("nan")
    realization_prior_rate = net_prior / gross_prior * 100 if gross_prior else 0.0
    realization_growth = pct(realization_rate, realization_prior_rate) if gross_prior else None
    asp_now = net_now / units_now if units_now else float("nan")
    asp_prior = net_prior / units_prior if units_prior else 0.0
    asp_growth = pct(asp_now, asp_prior) if units_prior else None
    store_channel_now = total(current[current.store_code != "(Unassigned)"], "net_sales_excl_gst")
    prior_active_stores = prior.loc[prior.store_code != "(Unassigned)", "store_code"].nunique() if not prior.empty else 0
    store_channel_prior = total(prior[prior.store_code != "(Unassigned)"], "net_sales_excl_gst") if not prior.empty else 0
    per_store = store_channel_now / active_stores if active_stores else float("nan")
    per_store_prior = store_channel_prior / prior_active_stores if prior_active_stores else 0.0
    per_store_growth = pct(per_store, per_store_prior) if per_store_prior else None

    context(f"Business dates: {start} → {end}", "INR · revenue excludes GST", "Latest available history")
    headline = st.columns(4)
    headline[0].metric("Net revenue (excl GST)", inr(net_now),
                       f"{net_growth:+.1f}% vs prior period" if net_growth is not None else None)
    headline[1].metric("Gross revenue", inr(gross_now),
                       f"{gross_growth:+.1f}% vs prior period" if gross_growth is not None else None)
    headline[2].metric("Net units", f"{units_now:,.0f}",
                       f"{units_growth:+.1f}% vs prior period" if units_growth is not None else None)
    headline[3].metric("Net revenue per net unit", inr(asp_now),
                       f"{asp_growth:+.1f}% vs prior period" if asp_growth is not None else None)
    st.markdown("#### Revenue composition")
    second = st.columns(4)
    second[0].metric("Net / gross ratio", f"{realization_rate:.1f}% of gross" if pd.notna(realization_rate) else "Not available",
                     f"{realization_growth:+.1f}% vs prior period" if realization_growth is not None else None)
    second[1].metric("Returns / gross ratio", f"{returns_rate:.1f}% of gross" if pd.notna(returns_rate) else "Not available",
                     f"{returns_growth:+.1f}% vs prior period" if returns_growth is not None else None,
                     delta_color="inverse")
    second[2].metric("Discount / gross ratio", f"{discount_rate:.1f}% of gross" if pd.notna(discount_rate) else "Not available",
                     f"{discount_growth:+.1f}% vs prior period" if discount_growth is not None else None,
                     delta_color="inverse")
    second[3].metric("Revenue per identified location", inr(per_store),
                     f"{per_store_growth:+.1f}% vs prior period" if per_store_growth is not None else None)
    if has_prior:
        st.caption(f"Window {start} to {end}; growth is against the preceding {span} days ({prior_start} to {prior_end}).")
    else:
        st.caption(f"Window {start} to {end}. Comparison is off or insufficient earlier history is available. A missing comparison is not zero growth.")
    st.caption("Ratios use the stored source amounts; gross and net may have different tax bases. Location counts include all identified store_code values. Net revenue per net unit is not a transaction-level selling price.")
    with st.expander("KPI definitions — how every number on this page is calculated"):
        st.markdown("""
| KPI | Definition | Source |
| --- | --- | --- |
| Net revenue (excl GST) | SUM of `net_sales_excl_gst` over the window | gold.daily_sales |
| Gross revenue | SUM of `gross_sales_amt` over the window | gold.daily_sales |
| Net units | SUM of `net_units` over the window | gold.daily_sales |
| Net revenue per net unit | Net revenue ÷ net units | derived |
| Net / gross ratio | Net revenue ÷ gross revenue × 100 — a source-value ratio; gross and net tax bases must be checked before interpreting it as retention | derived |
| Returns / gross ratio | SUM of `returns_excl_gst` ÷ gross revenue × 100 | derived |
| Discount / gross ratio | SUM of `sales_discount_amt` ÷ gross revenue × 100 | derived |
| Revenue per identified location | Net revenue with a non-null store_code ÷ distinct identified store_code values; may include online locations | derived |
| Growth | Window total versus the immediately preceding window of the same length | derived |
""")

    channel_now = current.groupby("channel", as_index=False)["net_sales_excl_gst"].sum().sort_values("net_sales_excl_gst", ascending=False)
    top_channel = channel_now.iloc[0]
    share_text = f" ({top_channel.net_sales_excl_gst / net_now * 100:.0f}% of net revenue)" if net_now else ""
    growth_text = f", {net_growth:+.1f}% versus the prior period" if net_growth is not None else ""
    ratio_text = f"{realization_rate:.1f}%" if pd.notna(realization_rate) else "not available (zero gross revenue)"
    insight(f"Stridewell booked {inr(net_now)} in net revenue across {selling_days} selling days{growth_text}. "
            f"{top_channel.channel} leads with {inr(top_channel.net_sales_excl_gst)}{share_text}, {active_stores} identified locations recorded sales in this window, "
            f"and the source net-to-gross ratio is {ratio_text}.")

    trend, mix = st.columns([1.7, 1])
    with trend, st.container(border=True):
        st.subheader("Net revenue trend")
        st.caption("Daily net sales excluding GST; rolling mean of observed sales within the preceding 7 calendar days")
        daily = current.groupby("business_date", as_index=False)["net_sales_excl_gst"].sum().sort_values("business_date")
        rolling_frame = daily.set_index(pd.to_datetime(daily.business_date))
        rolling = rolling_frame.net_sales_excl_gst.rolling("7D", min_periods=1).mean()
        fig = px.line(daily, x="business_date", y="net_sales_excl_gst", markers=True,
                      labels={"business_date": "Business date", "net_sales_excl_gst": "Net revenue"},
                      color_discrete_sequence=[COLORS[0]])
        fig.update_traces(line=dict(width=2))
        fig.add_scatter(x=daily.business_date, y=rolling, name="7-day average",
                        line=dict(color=COLORS[1], width=4))
        plot(fig)
    with mix, st.container(border=True):
        st.subheader("Channel mix")
        st.caption("Share of net revenue by channel")
        if (channel_now.net_sales_excl_gst >= 0).all() and net_now > 0:
            fig = px.pie(channel_now, names="channel", values="net_sales_excl_gst", hole=.7,
                         color_discrete_sequence=COLORS)
            fig.update_traces(textinfo="percent", textposition="outside",
                              hovertemplate="%{label}<br>%{value:,.0f}<br>%{percent}<extra></extra>")
            plot(fig)
        else:
            st.caption("Signed or zero net revenue: showing channel amounts instead of percentage shares.")
            plot(px.bar(channel_now,x="channel",y="net_sales_excl_gst",color_discrete_sequence=COLORS))
        growth_cards = st.columns(min(3, len(channel_now)))
        for i, (_, row) in enumerate(channel_now.iterrows()):
            card = growth_cards[i % len(growth_cards)]
            then_value = prior.loc[prior.channel == row.channel, "net_sales_excl_gst"].sum() if not prior.empty else 0
            card.metric(str(row.channel), inr(row.net_sales_excl_gst),
                        f"{pct(row.net_sales_excl_gst, then_value):+.1f}% vs prior" if then_value > 0 else None)

    store_sales = (current[current.store_code != "(Unassigned)"]
                   .groupby("store_code", as_index=False)["net_sales_excl_gst"].sum())
    left, right = st.columns(2)
    if not store_sales.empty:
        with left:
            bars(store_sales.nlargest(5, "net_sales_excl_gst"), "store_code",
                 "net_sales_excl_gst", "Top 5 identified locations")
        with right:
            bars(store_sales.nsmallest(5, "net_sales_excl_gst"), "store_code",
                 "net_sales_excl_gst", "Lowest 5 identified locations")

    risk, trust = st.columns(2)
    with risk, st.container(border=True):
        st.subheader("Inventory health")
        try:
            latest = query('SELECT MAX(snapshot_date) snapshot_date FROM IDENTIFIER(:source_table)', source=cover).iloc[0, 0]
            if pd.isna(latest):
                st.caption("No stock-cover snapshots are available yet.")
            else:
                status = query("SELECT COALESCE(stock_status, '(Unassigned)') stock_status,\n                    COUNT(*) record_count FROM IDENTIFIER(:source_table) WHERE snapshot_date = :snapshot\n                    GROUP BY 1 ORDER BY record_count DESC", {'snapshot': latest}, source=cover)
                out_of_stock = status.loc[status.stock_status == "OUT_OF_STOCK", "record_count"].sum()
                at_risk = status.loc[status.stock_status == "STOCKOUT_RISK_7D", "record_count"].sum()
                health = st.columns(2)
                health[0].metric("Out of stock", f"{out_of_stock:,.0f}")
                health[1].metric("Stockout risk (7d)", f"{at_risk:,.0f}")
                st.caption(f"{status.record_count.sum():,.0f} stock-cover records in this snapshot")
                st.caption(f"Latest snapshot {latest}. Counts are store/SKU records; the Stock Coverage page carries the drill-down.")
        except Exception:
            logging.warning("Executive stock-cover panel failed", exc_info=True)
            st.warning("Inventory health is unavailable. This is not a zero-risk result. Check the data source, permissions, or warehouse in the app logs.")
    with trust, st.container(border=True):
        st.subheader("Data trust")
        try:
            ledger_totals = query('SELECT COUNT(*) exception_count,\n                COALESCE(SUM(ABS(difference_inr)), 0) difference_inr FROM IDENTIFIER(:source_table)', source=ledger).iloc[0]
            trust_cards = st.columns(2)
            trust_cards[0].metric("Gold vs ERP exceptions", f"{ledger_totals.exception_count:,.0f}")
            trust_cards[1].metric("Absolute difference", inr(ledger_totals.difference_inr))
            st.caption("Scope: all retained business dates")
            st.caption("Reconciliation compares gold net sales with the ERP ledger; the Data Quality page carries the drill-down.")
        except Exception:
            logging.warning("Executive reconciliation panel failed", exc_info=True)
            st.warning("Reconciliation is unavailable. Data trust has not been assessed. Check the source, permissions, or warehouse in the app logs.")


def sales(overview=False):
    source = table("gold", "daily_sales")
    bounds = query('SELECT MIN(business_date) first_date, MAX(business_date) last_date FROM IDENTIFIER(:source_table)', source=source).iloc[0]
    if pd.isna(bounds.first_date):
        st.info("No sales records are available yet.")
        return
    preset = st.selectbox("Reporting period", ["Last 30 days", "Last 7 days", "Full history", "Custom dates"],key="sales_period")
    if preset == "Custom dates":
        selected = st.date_input("Business date range", (bounds.first_date, bounds.last_date),
                                 min_value=bounds.first_date,max_value=bounds.last_date,key="sales_custom")
    else:
        start = bounds.first_date if preset == "Full history" else max(bounds.first_date,bounds.last_date-timedelta(days=int(preset.split()[1])-1))
        selected = (start,bounds.last_date)
    context(f"Business dates: {selected[0]} → {selected[-1]}", "Blank filters include all values", "INR · latest available history")
    if len(selected) != 2:
        st.info("Select both a start and end date.")
        return
    frame = query('SELECT business_date, channel, store_code,\n        SUM(net_units) net_units, SUM(line_count) line_count,\n        SUM(gross_sales_amt) gross_sales_amt, SUM(sales_discount_amt) sales_discount_amt,\n        SUM(net_sales_excl_gst) net_sales_excl_gst,\n        SUM(returns_excl_gst) returns_excl_gst\n        FROM IDENTIFIER(:source_table) WHERE business_date BETWEEN :start AND :end\n        GROUP BY business_date, channel, store_code\n        ORDER BY business_date, channel, store_code LIMIT 10001', {'start': selected[0], 'end': selected[1]}, source=source)
    if len(frame) > 10000:
        st.warning("This selection is too large. Choose a shorter date range; totals have not been displayed.")
        return
    for column in ("channel", "store_code"):
        frame[column] = frame[column].fillna("(Unassigned)")
    left, right = st.columns(2)
    channels = left.multiselect("Channel", sorted(frame.channel.unique()))
    stores = right.multiselect("Store / channel location", sorted(frame.store_code.unique()))
    if channels:
        frame = frame[frame.channel.isin(channels)]
    if stores:
        frame = frame[frame.store_code.isin(stores)]
    if frame.empty:
        st.info("No sales match the selected filters.")
        return
    cards = st.columns(4)
    cards[0].metric("Net sales (excl GST)", inr(frame.net_sales_excl_gst.sum()))
    cards[1].metric("Gross sales", inr(frame.gross_sales_amt.sum()))
    cards[2].metric("Returns value", inr(frame.returns_excl_gst.sum()))
    cards[3].metric("Net units", f"{frame.net_units.sum():,.0f}")
    st.caption(f"Latest business date in source: {bounds.last_date}. Amounts use source currency; line count is not order count.")
    daily = frame.groupby("business_date", as_index=False)["net_sales_excl_gst"].sum()
    channel_totals = frame.groupby("channel", as_index=False)["net_sales_excl_gst"].sum()
    store_totals = frame.groupby("store_code", as_index=False)["net_sales_excl_gst"].sum()
    leader = channel_totals.sort_values("net_sales_excl_gst", ascending=False).iloc[0]
    peak = daily.loc[daily.net_sales_excl_gst.idxmax()]
    insight(f"{leader.channel} has the highest net sales in this selection. "
            f"The highest recorded sales day is {peak.business_date}, at {peak.net_sales_excl_gst:,.2f} excluding GST.")
    trend, mix = st.columns([1.7, 1])
    with trend, st.container(border=True):
        st.subheader("How are sales moving?")
        st.caption("Daily net sales · hover for exact values")
        fig = px.line(daily, x="business_date", y="net_sales_excl_gst", markers=True,
                      labels={"business_date":"Business date","net_sales_excl_gst":"Net sales"},
                      color_discrete_sequence=COLORS)
        fig.update_traces(line=dict(width=3), fill="tozeroy", fillcolor="rgba(8,127,140,0.08)")
        plot(fig)
    with mix, st.container(border=True):
        st.subheader("Where do sales come from?")
        if (channel_totals.net_sales_excl_gst >= 0).all() and channel_totals.net_sales_excl_gst.sum() > 0:
            fig = px.pie(channel_totals, names="channel", values="net_sales_excl_gst", hole=.7,
                         color_discrete_sequence=COLORS)
            fig.update_traces(textinfo='percent',textposition='outside',
                              hovertemplate='%{label}<br>%{value:,.2f}<br>%{percent}<extra></extra>')
            plot(fig)
        else:
            st.caption("Signed net sales are shown as bars because returns can make values negative.")
            plot(px.bar(channel_totals,x="channel",y="net_sales_excl_gst",color_discrete_sequence=COLORS))
    left, right = st.columns(2)
    with left:
        bars(store_totals.nlargest(10, "net_sales_excl_gst"), "store_code", "net_sales_excl_gst", "Top locations by net sales")
    with right, st.container(border=True):
        st.subheader("How many units moved?")
        units = frame.groupby("business_date", as_index=False)["net_units"].sum()
        plot(px.bar(units,x="business_date",y="net_units",color_discrete_sequence=[COLORS[1]],
                    labels={"business_date":"Business date","net_units":"Net units"}))
    if not overview:
        with st.container(border=True):
            st.subheader("Channel performance over time")
            by_channel = frame.groupby(["business_date","channel"],as_index=False)["net_sales_excl_gst"].sum()
            plot(px.line(by_channel,x="business_date",y="net_sales_excl_gst",color="channel",
                         color_discrete_sequence=COLORS,labels={"net_sales_excl_gst":"Net sales","business_date":"Business date"}))
    details(frame, filename="stridewell-sales.csv")


def inventory():
    source = table("gold", "daily_inventory")
    dates = query('SELECT DISTINCT snapshot_date FROM IDENTIFIER(:source_table) WHERE snapshot_date IS NOT NULL ORDER BY snapshot_date DESC LIMIT 366', source=source)
    if dates.empty:
        st.info("No inventory snapshots are available.")
        return
    snapshot = st.selectbox("Inventory snapshot date", dates.snapshot_date.tolist())
    context(f"Snapshot: {snapshot}", "Balances at one point in time", "Units, not currency")
    frame = query('SELECT location_type, location_code,\n        SUM(on_hand_qty) on_hand_qty, SUM(reserved_qty) reserved_qty,\n        SUM(inbound_in_transit_qty) inbound_in_transit_qty\n        FROM IDENTIFIER(:source_table) WHERE snapshot_date = :snapshot\n        GROUP BY location_type, location_code ORDER BY location_type, location_code', {'snapshot': snapshot}, source=source)
    types = st.multiselect("Location type", sorted(frame.location_type.dropna().unique()))
    if types:
        frame = frame[frame.location_type.isin(types)]
    if frame.empty:
        st.info("No inventory matches these filters.")
        return
    cards = st.columns(3)
    for card, label, column in zip(cards, ["On-hand units", "Reserved units", "Inbound units"],
                                   ["on_hand_qty", "reserved_qty", "inbound_in_transit_qty"]):
        card.metric(label, f"{frame[column].sum():,.0f}")
    st.caption("Balances refer to one snapshot only; inventory is not summed across dates.")
    insight(f"This view covers {len(frame):,} location/type records for {snapshot}. "
            "Reserved units are part of on-hand stock; inbound units have not arrived yet.")
    left, right = st.columns(2)
    inventory_chart = frame.copy()
    inventory_chart["location"] = inventory_chart.location_type.fillna("Unknown") + " · " + inventory_chart.location_code.fillna("Unknown")
    with left:
        bars(inventory_chart.nlargest(12,"on_hand_qty"),"location","on_hand_qty","Where is stock held?")
    with right, st.container(border=True):
        st.subheader("Stock by location type")
        grouped=frame.groupby("location_type",dropna=False)[["on_hand_qty","reserved_qty","inbound_in_transit_qty"]].sum().reset_index()
        melted=grouped.melt(id_vars="location_type",var_name="Balance",value_name="Units")
        melted["Balance"]=melted.Balance.map({"on_hand_qty":"On hand","reserved_qty":"Reserved","inbound_in_transit_qty":"Inbound"})
        plot(px.bar(melted,x="location_type",y="Units",color="Balance",barmode="group",color_discrete_sequence=COLORS))
        st.caption("Grouped balances are not additive: reserved stock is included in on hand.")
    details(frame,filename="stridewell-inventory.csv")


def coverage():
    source = table("gold", "stock_cover")
    latest = query('SELECT MAX(snapshot_date) snapshot_date FROM IDENTIFIER(:source_table)', source=source).iloc[0, 0]
    if pd.isna(latest):
        st.info("No stock-cover records are available.")
        return
    st.caption(f"Latest stock-cover snapshot: {latest}. Status definitions come from your existing pipeline.")
    summary = query("SELECT COALESCE(stock_status, '(Unassigned)') stock_status,\n        COUNT(*) record_count FROM IDENTIFIER(:source_table) WHERE snapshot_date = :snapshot\n        GROUP BY stock_status ORDER BY stock_status", {'snapshot': latest}, source=source)
    oos = summary.loc[summary.stock_status == "OUT_OF_STOCK", "record_count"].sum()
    at_risk = summary.loc[summary.stock_status == "STOCKOUT_RISK_7D", "record_count"].sum()
    cards=st.columns(4)
    cards[0].metric("Out of stock",f"{oos:,.0f}")
    cards[1].metric("Stockout risk (7d)",f"{at_risk:,.0f}")
    cards[2].metric("Stock-cover records",f"{summary.record_count.sum():,.0f}")
    cards[3].metric("Snapshot date",str(latest))
    bars(summary,"stock_status","record_count","How is stock coverage distributed?",color="stock_status")
    st.caption("Counts are stock-cover records, not distinct products across stores.")
    available=summary.stock_status.tolist()
    if not available:
        st.info("No stock statuses were returned for this date.")
        return
    focus = st.toggle("Prioritise stockout statuses",value=True,help="Moves existing out-of-stock and 7-day risk categories to the front. Does not redefine pipeline thresholds.")
    if focus:
        available=sorted(available,key=lambda x: (0 if x=="OUT_OF_STOCK" else 1 if x=="STOCKOUT_RISK_7D" else 2,str(x)))
    status = st.selectbox("Inspect a status",available)

    detail = query("SELECT store_code, sku, on_hand_qty, inbound_in_transit_qty,\n        avg_weekly_units, weeks_of_cover, stock_status FROM IDENTIFIER(:source_table)\n        WHERE snapshot_date = :snapshot AND COALESCE(stock_status, '(Unassigned)') = :status\n        ORDER BY weeks_of_cover ASC NULLS LAST, store_code, sku LIMIT 500", {'snapshot': latest, 'status': status}, source=source)
    usable=detail.dropna(subset=["weeks_of_cover", "avg_weekly_units"]).copy()
    if not usable.empty:
        with st.container(border=True):
            st.subheader("Demand and stock coverage")
            st.caption("Each point is one store/product record from the selected preview. Hover to identify it.")
            plot(px.scatter(usable,x="avg_weekly_units",y="weeks_of_cover",hover_data=["store_code","sku","on_hand_qty"],
                            color_discrete_sequence=COLORS,
                            labels={"avg_weekly_units":"Average weekly units","weeks_of_cover":"Weeks of cover"}))
    details(detail,"Inspect store and product records","stridewell-stock-cover.csv")
    st.caption("Detail preview is limited to 500 records. No replenishment approvals or write-back are implemented.")


def recon():
    source = table("ops", "recon_exceptions")
    try:
        frame = query("SELECT COALESCE(exception_type, '(Unassigned)') exception_type,\n            COUNT(*) exception_count, SUM(ABS(difference_inr)) difference_inr\n            FROM IDENTIFIER(:source_table) GROUP BY 1 ORDER BY exception_count DESC", source=source)
    except Exception:
        logging.warning("Reconciliation query failed", exc_info=True)
        st.warning("Reconciliation is unavailable. Check access to ops.recon_exceptions, its schema, and warehouse availability. No match or mismatch conclusion can be drawn.")
        return
    context("Scope: all retained business dates", "Absolute differences · INR", "Read-only review")
    cards = st.columns(3)
    cards[0].metric("Reconciliation exceptions", f"{frame.exception_count.sum():,.0f}")
    cards[1].metric("Absolute difference", inr(frame.difference_inr.sum()))
    cards[2].metric("Exception types", str(len(frame)))
    if frame.empty:
        st.info("No exception records were returned. This alone does not confirm that all reconciliation checks ran or passed.")
        return
    lead = frame.iloc[0]
    insight(f"{frame.exception_count.sum():,.0f} exception records are retained for gold-versus-ERP checks, "
            f"totalling {inr(frame.difference_inr.sum())} in absolute difference. The most common gap is {lead.exception_type} "
            f"with {lead.exception_count:,.0f} exception records.")
    bars(frame.head(10), "exception_type", "exception_count", "Where does gold disagree with the ERP ledger?")
    details(frame, "Inspect reconciliation exceptions", "stridewell-recon.csv")


def quality():
    choices = {"POS sales": "quarantine_pos_sales", "E-commerce events": "quarantine_ecom_events"}
    label = st.selectbox("Source", list(choices))
    source = table("silver", choices[label])
    frame = query("SELECT COALESCE(dq_reason, '(No reason supplied)') dq_reason,\n        COUNT(*) record_count FROM IDENTIFIER(:source_table) GROUP BY dq_reason ORDER BY record_count DESC", source=source)
    cards=st.columns(3)
    cards[0].metric("Quarantined records",f"{frame.record_count.sum():,.0f}")
    cards[1].metric("Reason groups",str(len(frame)))
    cards[2].metric("Selected source",label)
    if frame.empty:
        st.success("No quarantined records were returned for this source.")
        return
    main=frame.iloc[0]
    insight(f"The largest stored reason group contains {main.record_count:,.0f} records. "
            "Review the reason breakdown below to decide which source rules to investigate.")
    chart=frame.head(10).copy()
    chart['Reason']=[f'{i+1}. {str(v)[:65]}' + ('…' if len(str(v))>65 else '') for i,v in enumerate(chart.dq_reason)]
    with st.container(border=True):
        st.subheader("What is preventing records from passing validation?")
        fig=px.bar(chart,x="record_count",y="Reason",orientation="h",hover_data=["dq_reason"],color_discrete_sequence=['#d68b36'])
        fig.update_yaxes(categoryorder='total ascending')
        plot(fig,height=max(340,min(600,55*len(chart))))
        st.caption("Top 10 stored reason groups. Expand the records below for full reason text.")
    st.caption("All records currently retained in this quarantine table. This is not a daily failure count or a failure rate. Reason strings are shown as stored.")
    details(frame, "Inspect all validation reasons", "stridewell-quality.csv")



def ask_ai():
    if not GENIE_SPACE_ID:
        st.info("The AI assistant is not configured yet. Add GENIE_SPACE_ID in app.yaml and redeploy.")
        return
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    for role, text, sql in st.session_state.chat_history:
        with st.chat_message(role):
            st.markdown(text)
            if sql:
                st.caption("Query the assistant ran")
                st.code(sql, language="sql")
    question = st.chat_input("Ask about Stridewell sales, inventory, stock coverage or reconciliation…")
    if question:
        st.session_state.chat_history.append(("user", question, None))
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Analysing Stridewell data…"):
                try:
                    answer, sql_text = ask_genie(question)
                except Exception:
                    logging.exception("Genie assistant call failed")
                    answer, sql_text = ("The assistant is unavailable right now. Check the Genie space sharing and warehouse access, then try again.", None)
            st.markdown(answer)
            if sql_text:
                st.caption("Query the assistant ran")
                st.code(sql_text, language="sql")
        st.session_state.chat_history.append(("assistant", answer, sql_text))


def requirements():
    st.markdown("### Find the answer you need")
    st.caption("This map describes the capabilities present in your uploaded application. It is not a claim that every original case-study requirement is complete.")
    mapping = pd.DataFrame([
        ["How is the business performing?", "Executive", "Revenue, units, equal-length period comparisons, channel mix", "gold.daily_sales"],
        ["Where are sales happening?", "Overview / Sales", "Dates, channels, location filters and trends", "gold.daily_sales"],
        ["Where is our stock?", "Inventory", "On hand, reserved and inbound at one snapshot", "gold.daily_inventory"],
        ["Which stock needs review?", "Stock Coverage", "Existing pipeline statuses and product/store preview", "gold.stock_cover"],
        ["Why did records fail validation?", "Data Quality", "Retained quarantine records grouped by reason", "silver quarantine tables"],
        ["Where do financial totals differ?", "Reconciliation", "Exception counts and absolute differences", "ops.recon_exceptions"],
    ],columns=["Business question","Go to","What you can inspect","Source"])
    for _, row in mapping.iterrows():
        with st.container(border=True):
            a,b=st.columns([4,1])
            a.markdown("**"+row["Business question"]+"**")
            a.caption(row["What you can inspect"]+" · "+row["Source"])
            destination="Sales" if row["Go to"]=="Overview / Sales" else row["Go to"]
            b.button("Open →",key="guide_"+destination,on_click=go_to,args=(destination,),width="stretch")
    st.markdown("### What the app does not establish yet")
    st.info("Replenishment approvals, order-level KPIs, product/category sales analysis, inventory ageing and sell-through are not implemented in this uploaded version. Their absence is explicit; no placeholder business numbers are shown.")
    st.markdown("### Read the numbers correctly")
    st.markdown("""- **Business dates** are dates in your dataset; refresh does not load new source files or run pipelines.
- **Sales lines are not orders.** Net units may include returns.
- **Missing data is not zero.** An unavailable panel cannot establish good performance or low risk.
- **Inventory is a snapshot.** Reserved units are included in on-hand stock; do not add them together.
- **Quarantine counts include retained history.** They are not today's failure count or a failure percentage.
- **Reconciliation shows exceptions only.** Zero returned rows does not prove that all scheduled checks completed.
- **Comparison deltas** require earlier history and a positive baseline. Ratios are derived from stored amounts with potentially different tax bases.
- **Downloads** contain the matching records already loaded on that page, with any detail limit stated alongside the view.""")


def go_to(destination):
    st.session_state.main_nav=destination


with st.sidebar:
    st.markdown("### Workspace preferences")
    st.toggle("Compact layout",key="compact_mode",help="Smaller cards and charts for a denser workspace.")
    st.toggle("Chart labels",value=True,key="chart_labels",help="Show or hide text labels; hover details remain available.")
    st.toggle("Full currency values",key="full_amounts",help="Show full INR amounts instead of lakh/crore abbreviations.")
    st.toggle("Compare periods",value=True,key="compare_periods",help="Executive metrics compare with the immediately preceding equal-length period.")
    st.divider()
    st.caption("Filters belong to the page where they are shown. Refresh clears cached query results; it does not refresh pipelines.")
    st.caption("This app reads data using its service principal. Individual user/store restrictions are not implemented.")

brand,appearance,guidance,refresh=st.columns([5,1.35,1.45,1.45],vertical_alignment="center")
with brand:
    st.html('<div class="sw-brand"><span class="sw-mark">s</span><div class="sw-wordmark">stridewell<small>RETAIL INTELLIGENCE</small></div></div>')
with appearance: st.toggle("Dark mode",key="dark_mode")
with guidance: st.toggle("Explain data",value=True,key="guided_mode",help="Show plain-language observations next to charts.")
with refresh:
    if st.button("↻ Refresh",width="stretch"):
        query.clear()
        st.session_state.refreshed_at=datetime.now(timezone.utc).strftime("%H:%M UTC")
style()
page=st.radio("Navigate workspace",["Executive","Overview","Sales","Inventory","Stock Coverage","Data Quality","Reconciliation","Guide","Ask AI"],horizontal=True,key="main_nav",label_visibility="collapsed")
headings={
    "Executive":("A clear view of your business.","Revenue, channel performance, inventory exposure and financial exceptions — together in one executive view."),
    "Overview":("Understand the sales story.","Start with the big picture. See how sales move, which channels contribute and where demand is strongest."),
    "Sales":("Turn sales patterns into answers.","Choose a period, channel or location to explore the performance behind the totals."),
    "Inventory":("Know where your stock stands.","A point-in-time view of on-hand, reserved and inbound inventory across your locations."),
    "Stock Coverage":("Focus on stock that needs review.","Inspect your pipeline's stock statuses, then explore demand and coverage by store and product."),
    "Data Quality":("Understand what needs fixing.","See retained validation issues by source and reason, with searchable evidence for investigation."),
    "Reconciliation":("Make financial differences visible.","Review stored gold-versus-ERP exceptions. Identify the most frequent differences before investigating the source."),
    "Guide":("Every page has a purpose.","Find the business question, the right view, and the meaning behind each result."),
    "Ask AI":("Ask your data, directly.","A conversational assistant over your Stridewell tables — ask a business question in plain language and get an answer, with the query behind it.")}
hero(*headings[page])
if st.session_state.get("refreshed_at"):
    st.caption("Cache cleared at "+st.session_state.refreshed_at+" · business dates are shown separately below")
if page=="Guide":
    requirements()
elif page=="Ask AI":
    ask_ai()
elif not WAREHOUSE:
    st.warning("Data connection is not configured. Attach your SQL warehouse as sql-warehouse and redeploy. No business results have been loaded.")
else:
    try:
        with st.spinner("Reading your Stridewell data…"):
            {"Executive":executive,"Overview":lambda:sales(overview=True),"Sales":sales,"Inventory":inventory,
             "Stock Coverage":coverage,"Data Quality":quality,"Reconciliation":recon}[page]()
    except Exception:
        logging.exception("Stridewell dashboard query failed")
        st.error("This view could not load. Check the warehouse, source table and app permissions in the logs, then use Refresh. No result should be inferred from this error.")
st.html('<div class="sw-footer">STRIDEWELL &nbsp; / &nbsp; Read-only business workspace &nbsp; · &nbsp; Query cache: up to 5 minutes &nbsp; · &nbsp; Use Guide for definitions and coverage</div>')
