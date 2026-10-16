import streamlit as st
import pandas as pd
import re

st.set_page_config(page_title="Xtra + SSR (Based on 10KG)", layout="wide")

st.title("Xtra + SSR (Based on 10KG)")
st.caption(
    "Paste the SSR-ticked Passenger List (copied straight from the Airblue system) below. "
    "The app reports two separate things: how many passengers have FC = EX (fare class), "
    "and how many passengers have an SSR of XB10 / XB20 / XB30 (extra baggage requests), "
    "with an extra-baggage-unit total (XB10 = 1, XB20 = 2, XB30 = 3)."
)

# ---- SSR code -> extra bag units (10kg blocks) ----
SSR_UNITS = {
    "XB10": 1,
    "XB20": 2,
    "XB30": 3,
}

STATUS_WORDS = {"USED", "NOSHOW", "CNL", "CANCELLED", "WAIT", "STANDBY", "GOSHOW", "OPEN"}

ROW_START_PATTERN = re.compile(r"^\s*\d+\s")


def merge_wrapped_lines(raw_text: str):
    """
    When copied from the browser, trailing columns (SSR, Customs Response)
    often wrap onto their own line below the row that produced them
    (e.g. a row ending in '...USED' followed on the next line by just
    'XB20'). This stitches those continuation lines back onto the row
    they belong to, so each logical passenger row is one string again.
    """
    lines = raw_text.splitlines()
    merged = []
    buffer = None

    for line in lines:
        if ROW_START_PATTERN.match(line):
            if buffer is not None:
                merged.append(buffer)
            buffer = line.rstrip()
        else:
            if buffer is not None and line.strip():
                buffer += "\t" + line.strip()
            # lines before the first row (headers, filters, etc.) are dropped

    if buffer is not None:
        merged.append(buffer)

    return merged


def parse_passenger_list(raw_text: str) -> pd.DataFrame:
    """
    Parses the passenger list table copied from the Airblue system (with
    the SSR checkbox ticked). Column layout:
        ... FC | BA | Bags | Carry | Status | SSR (one or more codes)
    A passenger can have multiple SSR codes stacked (e.g. "SEAT" and
    "XB20" both requested), each wrapping onto its own line, so we can't
    assume a fixed number of trailing fields. Instead we locate the
    Status word (USED/NOSHOW/etc.) explicitly - FC always sits exactly
    4 fields before it (FC, BA, Bags, Carry, Status) - and treat
    everything after Status as SSR code(s).
    """
    rows = []

    for line in merge_wrapped_lines(raw_text):
        if "\t" not in line:
            continue  # can't reliably locate columns without tabs

        parts = line.split("\t")

        # Row must start with a row number
        if not re.match(r"^\s*\d+\s*$", parts[0]):
            continue

        # Find the Status word - search from the right since it's near
        # the end, but don't assume a fixed offset (trailing SSR tokens
        # vary in count).
        status_idx = None
        for i in range(len(parts) - 1, -1, -1):
            if parts[i].strip().upper() in STATUS_WORDS:
                status_idx = i
                break

        if status_idx is None or status_idx < 4:
            continue

        fc = parts[status_idx - 4].strip().upper()

        ssr_tokens = [p.strip().upper() for p in parts[status_idx + 1:] if p.strip() != ""]

        pnr = parts[1].strip() if len(parts) > 1 else ""
        name = parts[2].strip() if len(parts) > 2 else ""
        title = parts[3].strip() if len(parts) > 3 else ""
        gender = parts[4].strip().upper() if len(parts) > 4 else ""
        is_infant = gender == "I"

        # A row's SSR requests may include several codes (e.g. SEAT + XB20).
        # Sum extra-bag units across all baggage-related codes present.
        extra_units = sum(SSR_UNITS.get(tok, 0) for tok in ssr_tokens)
        xb_codes_present = [tok for tok in ssr_tokens if tok in SSR_UNITS]

        rows.append({
            "PNR": pnr,
            "Passenger": name,
            "Title": title,
            "Infant": is_infant,
            "FC": fc,
            "SSR": ", ".join(ssr_tokens) if ssr_tokens else "",
            "XB Codes": ", ".join(xb_codes_present) if xb_codes_present else "",
            "Extra Bag Units": extra_units,
        })

    return pd.DataFrame(rows)


def parse_report_totals(raw_text: str) -> dict:
    """
    Pulls summary figures from the bottom of the report:
      - USED (travel load) from the PASSENGER TOTALS -> TOTALS: row
      - Allowance, Weight, Average KG per Piece and Average KG per Passenger
        from BAGGAGE TOTALS
    """
    result = {}
    lines = raw_text.splitlines()

    # ---- USED (travel load) from PASSENGER TOTALS -> TOTALS: row ----
    pt_idx = None
    for i, l in enumerate(lines):
        if l.strip().startswith("PASSENGER TOTALS"):
            pt_idx = i
            break

    if pt_idx is not None:
        totals_idx = None
        for i in range(pt_idx, min(pt_idx + 40, len(lines))):
            if lines[i].strip() == "TOTALS:":
                totals_idx = i
                break
        if totals_idx is not None:
            values = []
            j = totals_idx + 1
            while len(values) < 5 and j < len(lines):
                values.append(lines[j].strip())
                j += 1
            if len(values) == 5:
                used_line = values[4]
                m = re.match(r"(\d+)", used_line)
                if m:
                    result["used_total"] = int(m.group(1))
                    result["used_raw"] = used_line

    # ---- BAGGAGE TOTALS ----
    m = re.search(r"Allowance:\s*\t?\s*([\d,]+)", raw_text)
    if m:
        result["allowance"] = m.group(1)

    m = re.search(r"Weight:\s*\t?\s*([\d,.]+kg)\s*\t?\s*([\d,.]+kg)?", raw_text)
    if m:
        result["weight_checked"] = m.group(1)
        result["weight_carry"] = m.group(2) or ""

    m = re.search(r"Average KG per Piece:\s*\t?\s*([\d,.]+kg)", raw_text)
    if m:
        result["avg_piece_checked"] = m.group(1)

    m = re.search(r"Average KG per Passenger:\s*\t?\s*([\d,.]+kg)\s*\t?\s*([\d,.]+kg)?", raw_text)
    if m:
        result["avg_checked"] = m.group(1)
        result["avg_carry"] = m.group(2) or ""

    return result


def parse_cfp(raw_text: str) -> dict:
    """
    Parses a CFP (flight plan) text file for:
      - EST TOGW (CFP TOGW)
      - PAYLOAD
      - BLK FUEL
      - ALT STN (uses ALT STN 1; falls back to ALT STN 2 if 1 is empty/blank/dashes)
    """
    result = {}

    m = re.search(r"PAYLOAD\s*:\s*(\d+)", raw_text)
    if m:
        result["payload"] = m.group(1)

    m = re.search(r"EST TOGW\s*:\s*(\d+)", raw_text)
    if m:
        result["togw"] = m.group(1)

    m = re.search(r"BLK FUEL\s*:\s*(\d+)", raw_text)
    if m:
        result["blk_fuel"] = m.group(1)

    m = re.search(r"AVG W/C\s*:\s*(\S+)", raw_text)
    if m:
        result["wc"] = m.group(1)

    m1 = re.search(r"ALT STN 1\s*:\s*(\S+)", raw_text)
    m2 = re.search(r"ALT STN 2\s*:\s*(\S+)", raw_text)
    alt1 = m1.group(1) if m1 else ""
    alt2 = m2.group(1) if m2 else ""

    def is_empty(v):
        return (not v) or v.strip("-") == "" or v.upper() in ("N/A", "NONE")

    if not is_empty(alt1):
        result["alt_stn"] = alt1
        result["alt_stn_source"] = "ALT STN 1"
    elif not is_empty(alt2):
        result["alt_stn"] = alt2
        result["alt_stn_source"] = "ALT STN 2"
    else:
        result["alt_stn"] = ""
        result["alt_stn_source"] = "none"

    return result


def kg_to_num(s):
    m = re.search(r"[\d,.]+", s or "")
    return float(m.group().replace(",", "")) if m else None


def pick_highest_kg(*values):
    """Returns the original string (e.g. '22kg') with the highest numeric value."""
    scored = [(kg_to_num(v), v) for v in values if kg_to_num(v) is not None]
    return max(scored, key=lambda x: x[0])[1] if scored else "N/A"


raw_text = st.text_area(
    "Paste passenger list data here",
    height=350,
    placeholder="Paste the copied SSR-ticked passenger list table here...",
)

uploaded_file = st.file_uploader("...or upload a saved .txt file", type=["txt"])
if uploaded_file is not None:
    raw_text = uploaded_file.read().decode("utf-8", errors="ignore")

# Shared across sections for the final combined copy-paste summary at the bottom
total_xb_units = None
ex_fc_count_final = None
totals = {}
cfp_data = {}

if raw_text and raw_text.strip():
    df_all = parse_passenger_list(raw_text)

    if df_all.empty:
        st.warning("No recognizable passenger rows found. Check the pasted format.")
    else:
        rows_with_ssr = int((df_all["SSR"] != "").sum())
        total_rows = len(df_all)

        if rows_with_ssr == 0:
            st.error(
                "⚠️ SSR is not ticked. None of the pasted rows have any SSR value at all "
                "(not even 'SEAT'), which means the SSR checkbox wasn't ticked when this "
                "was copied from the Airblue system. Please tick the SSR checkbox on the "
                "Passenger List page, copy the table again, and re-paste it here — otherwise "
                "the XB10/XB20/XB30 numbers below cannot be trusted."
            )
        elif rows_with_ssr / total_rows < 0.5:
            st.warning(
                f"⚠️ Only {rows_with_ssr} of {total_rows} rows have an SSR value. "
                "This is lower than expected — double-check that the SSR checkbox was "
                "ticked before copying, since some rows may be missing SSR data."
            )

        df_adults = df_all[~df_all["Infant"]].reset_index(drop=True)
        infant_count = int(df_all["Infant"].sum())

        ex_fc_count = int((df_adults["FC"] == "EX").sum())
        ex_fc_count_final = ex_fc_count
        xb_df = df_adults[df_adults["XB Codes"] != ""].reset_index(drop=True)
        total_xb_units = int(xb_df["Extra Bag Units"].sum())

        if infant_count:
            st.caption(f"Note: {infant_count} infant passenger(s) excluded from the counts below.")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("FC = EX (fare class) passengers", ex_fc_count)
        with col2:
            st.metric("Extra Bag Units from SSR (XB10/20/30)", total_xb_units)

        totals = parse_report_totals(raw_text)
        if totals:
            st.subheader("Report Totals")
            t1, t2, t3, t4 = st.columns(4)
            with t1:
                if "used_total" in totals:
                    st.metric("Travel Load (USED)", totals["used_raw"])
                else:
                    st.metric("Travel Load (USED)", "N/A")
            with t2:
                st.metric("Allowance (kg)", totals.get("allowance", "N/A"))
            with t3:
                st.metric(
                    "Total Weight (Checked / Carry-On)",
                    f'{totals.get("weight_checked", "N/A")} / {totals.get("weight_carry", "N/A")}',
                )
            with t4:
                st.metric(
                    "Avg KG per Passenger (Checked / Carry-On)",
                    f'{totals.get("avg_checked", "N/A")} / {totals.get("avg_carry", "N/A")}',
                )

        st.subheader("SSR Breakdown (XB10 / XB20 / XB30)")
        if not xb_df.empty:
            st.dataframe(xb_df, use_container_width=True, hide_index=True)
        else:
            st.info("No XB10 / XB20 / XB30 SSR requests found.")

        st.subheader("FC = EX Passengers")
        ex_fc_df = df_adults[df_adults["FC"] == "EX"].reset_index(drop=True)
        if not ex_fc_df.empty:
            st.dataframe(ex_fc_df, use_container_width=True, hide_index=True)
        else:
            st.info("No passengers with FC = EX found.")

        csv = df_all.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download full parsed data (CSV)",
            data=csv,
            file_name="passenger_list_parsed.csv",
            mime="text/csv",
        )

        with st.expander("Show all parsed rows"):
            st.dataframe(df_all, use_container_width=True, hide_index=True)
else:
    st.info("Paste passenger list data above to see results.")

st.divider()
st.header("CFP Data (TOGW / Payload / BLK FUEL / ALT STN)")
st.caption(
    "Attach the CFP (flight plan) .txt file to pull EST TOGW, PAYLOAD, BLK FUEL, and the "
    "alternate station (ALT STN 1, falling back to ALT STN 2 if ALT STN 1 is empty)."
)

cfp_file = st.file_uploader("Attach CFP .txt file", type=["txt"], key="cfp_uploader")
if cfp_file is not None:
    cfp_text = cfp_file.read().decode("utf-8", errors="ignore")
    cfp_data = parse_cfp(cfp_text)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("CFP TOGW (EST TOGW)", cfp_data.get("togw", "N/A"))
    with c2:
        st.metric("Payload", cfp_data.get("payload", "N/A"))
    with c3:
        st.metric("BLK FUEL", cfp_data.get("blk_fuel", "N/A"))
    with c4:
        st.metric("W/C", cfp_data.get("wc", "N/A"))
    with c5:
        alt_label = f'ALT STN ({cfp_data.get("alt_stn_source", "N/A")})'
        st.metric(alt_label, cfp_data.get("alt_stn") or "N/A")
else:
    st.info("Attach a CFP .txt file above to see TOGW, Payload, BLK FUEL, and ALT STN.")

st.divider()
st.header("Final Summary (Copy-Paste Row)")
st.caption(
    "Sequence: CFP TOGW, Payload, BLK Fuel, W/C, Alternate, Avg Bag, Travel Load, "
    "Total Baggage Weight, Total Allowance, Xtra+SSR. Alternate and Avg Bag are shown "
    "for reference only (dropdown / manual entry) and are excluded from the copyable row below."
)

summary_row = {
    "CFP TOGW": cfp_data.get("togw", "N/A"),
    "Payload": cfp_data.get("payload", "N/A"),
    "BLK Fuel": cfp_data.get("blk_fuel", "N/A"),
    "W/C": cfp_data.get("wc", "N/A"),
    "Alternate": cfp_data.get("alt_stn") or "N/A",
    "Avg Bag": "Do manually",
    "Travel Load": totals.get("used_raw", "N/A"),
    "Avg KG per Passenger": pick_highest_kg(totals.get("avg_piece_checked"), totals.get("avg_checked")),
    "Total Baggage Weight": totals.get("weight_checked", "N/A"),
    "Total Allowance": totals.get("allowance", "N/A"),
    "Xtra+SSR": (
        ex_fc_count_final + total_xb_units
        if ex_fc_count_final is not None and total_xb_units is not None
        else "N/A"
    ),
}

st.dataframe(pd.DataFrame([summary_row]), use_container_width=True, hide_index=True)

# Copyable row excludes Alternate (dropdown - selected manually) and Avg Bag (manual entry)
copy_fields = [
    "CFP TOGW", "Payload", "BLK Fuel", "W/C",
    "Travel Load", "Avg KG per Passenger", "Total Baggage Weight", "Total Allowance", "Xtra+SSR",
]
copy_line = "\t".join(str(summary_row[f]) for f in copy_fields)

st.caption("Copy this row (Alternate and Avg Bag excluded — enter those two manually):")
st.code(copy_line, language=None)
