"""Theme-aware presentation. No data access or synthetic business values."""
from html import escape
import math
import pandas as pd
import plotly.express as px
import streamlit as st

COLORS = ['#16a394', '#6d7bea', '#d99537', '#dc6679', '#51a9d3', '#a47dda']
STATUS_COLORS={'OUT_OF_STOCK':'#dc6679','STOCKOUT_RISK_7D':'#d99537','HEALTHY':'#16a394','OVERSTOCK':'#6d7bea','(Unassigned)':'#8b98a9'}

def palette():
    if st.session_state.get('dark_mode',False):
        return dict(bg='#0c1422',surface='#131f31',raised='#1b2a40',text='#e8eff9',muted='#a5b5cc',line='#2b3b53',accent='#51d7c6',soft='#153635',shadow='#00000020')
    return dict(bg='#f4f7fb',surface='#ffffff',raised='#edf2f8',text='#172c46',muted='#5b6d84',line='#dce5ef',accent='#087e73',soft='#e7f5f1',shadow='#263b5708')

def inr(value):
    try: value=float(value)
    except (TypeError,ValueError): return '—'
    if not math.isfinite(value): return '—'
    sign='−' if value<0 else ''; size=abs(value)
    if st.session_state.get('full_amounts',False): return f'{sign}₹{size:,.2f}'
    if size>=10_000_000: return f'{sign}₹{size/10_000_000:,.2f} Cr'
    if size>=100_000: return f'{sign}₹{size/100_000:,.2f} L'
    return f'{sign}₹{size:,.0f}'

def style():
    p=palette(); compact=st.session_state.get('compact_mode',False)
    css='''
    :root {--sw-bg:BG;--sw-surface:SURFACE;--sw-raised:RAISED;--sw-text:TEXT;--sw-muted:MUTED;--sw-line:LINE;--sw-accent:ACCENT;--sw-soft:SOFT;}
    .stApp,[data-testid="stAppViewContainer"] {background:var(--sw-bg);color:var(--sw-text);}
    [data-testid="stHeader"] {display:none;}
    [data-baseweb="select"] svg,[data-testid="stExpander"] svg {color:var(--sw-muted);fill:var(--sw-muted);}
    .block-container {max-width:1536px;padding:1.6rem 2.8rem 3rem;}
    h1,h2,h3,h4,p,label,summary {color:var(--sw-text);}
    [data-testid="stCaptionContainer"] p {color:var(--sw-muted)!important;}
    [data-testid="stSidebar"] {background:var(--sw-surface);border-right:1px solid var(--sw-line);}
    [data-testid="stSidebar"] * {color:var(--sw-text);}
    [data-testid="stMetric"] {background:var(--sw-surface);border:1px solid var(--sw-line);border-radius:14px;padding:PAD;box-shadow:0 3px 16px SHADOW;min-height:132px;}
    [data-testid="stMetricLabel"] p {font-size:12px;font-weight:600;color:var(--sw-muted);}
    [data-testid="stMetricValue"] {font-size:clamp(20px,2.15vw,34px);font-weight:700;letter-spacing:-1px;color:var(--sw-text);}
    [data-testid="stMetricDelta"] {font-size:11px;}
    [data-testid="stVerticalBlockBorderWrapper"]>div,[data-testid="stExpander"] {background:var(--sw-surface);border-color:var(--sw-line)!important;border-radius:16px;}
    [data-testid="stExpander"] summary:hover {color:var(--sw-accent);}
    [data-baseweb="select"]>div,[data-baseweb="input"],[data-baseweb="base-input"],input {background:var(--sw-surface)!important;color:var(--sw-text)!important;border-color:var(--sw-line)!important;}
    [data-baseweb="popover"],[data-baseweb="popover"]>div,[role="listbox"],[role="option"],[data-baseweb="calendar"] {background:var(--sw-surface)!important;color:var(--sw-text)!important;}
    [role="option"]:hover {background:var(--sw-raised)!important;}
    [data-baseweb="tag"] {background:var(--sw-soft)!important;color:var(--sw-accent)!important;}
    [data-testid="stButton"] button,[data-testid="stDownloadButton"] button {background:var(--sw-surface);color:var(--sw-text);border:1px solid var(--sw-line);border-radius:9px;}
    [data-testid="stButton"] button:hover,[data-testid="stDownloadButton"] button:hover {border-color:var(--sw-accent);color:var(--sw-accent);}
    button:focus-visible,input:focus-visible {outline:2px solid var(--sw-accent)!important;outline-offset:3px;}
    .st-key-main_nav [role="radiogroup"] {display:flex;gap:6px;padding:8px;background:var(--sw-surface);border:1px solid var(--sw-line);border-radius:13px;flex-wrap:wrap;}
    .st-key-main_nav [role="radiogroup"]>label {padding:8px 14px;margin:0;border-radius:8px;transition:background .15s;}
    .st-key-main_nav [role="radiogroup"]>label>div:first-child {display:none;}
    .st-key-main_nav [role="radiogroup"]>label:has(input:checked) {background:var(--sw-soft);box-shadow:inset 0 -2px var(--sw-accent);}
    .st-key-main_nav [role="radiogroup"]>label:has(input:checked) p {color:var(--sw-accent);font-weight:700;}
    .st-key-main_nav [role="radiogroup"]>label:has(input:focus-visible) {outline:2px solid var(--sw-accent);}
    .st-key-main_nav [role="radiogroup"]>label:hover {background:var(--sw-raised);}
    .sw-brand {display:flex;align-items:center;gap:12px;padding:3px 0 8px;}
    .sw-mark {width:39px;height:39px;border-radius:12px;background:linear-gradient(135deg,#118f85,#264e79);color:white;font-weight:800;font-size:23px;display:grid;place-items:center;box-shadow:0 4px 18px #118f8525;}
    .sw-wordmark {font-size:25px;font-weight:800;letter-spacing:-1.2px;line-height:1;color:var(--sw-text);}
    .sw-brand small {display:block;font-size:9px;font-weight:600;letter-spacing:2px;color:var(--sw-muted);margin-top:6px;}
    .hero {border-bottom:1px solid var(--sw-line);padding:20px 0 24px;margin-bottom:18px;background:radial-gradient(ellipse at 100% 0%,#16a3940b,transparent 65%);}
    .hero h1 {font-size:clamp(27px,3vw,39px);letter-spacing:-1.4px;font-weight:750;line-height:1.2;margin:7px 0;color:var(--sw-text);}
    .hero p {color:var(--sw-muted);font-size:14px;max-width:850px;line-height:1.7;margin:0;}
    .eyebrow {text-transform:uppercase;font-size:10px;letter-spacing:2px;color:var(--sw-accent);font-weight:700;}
    .insight {background:var(--sw-soft);border:1px solid var(--sw-line);border-radius:12px;padding:16px 20px;margin:12px 0 20px;color:var(--sw-text);font-size:14px;line-height:1.65;}
    .insight b {color:var(--sw-accent);font-size:10px;letter-spacing:1.8px;display:block;margin-bottom:3px;}
    h3 {font-size:18px!important;letter-spacing:-.35px;}
    .sw-context {display:flex;gap:8px;flex-wrap:wrap;margin:3px 0 20px;}
    .sw-chip {background:var(--sw-surface);color:var(--sw-muted);border:1px solid var(--sw-line);border-radius:6px;padding:5px 10px;font-size:11px;}
    .sw-table-wrap {overflow:auto;border:1px solid var(--sw-line);border-radius:10px;max-height:500px;}
    table.sw-table {width:100%;border-collapse:collapse;color:var(--sw-text);font-size:12px;white-space:nowrap;}
    .sw-table th {text-align:left;background:var(--sw-raised);color:var(--sw-muted);font-size:11px;position:sticky;top:0;}
    .sw-table td,.sw-table th {padding:11px 14px;border-bottom:1px solid var(--sw-line);}
    .sw-table tr:nth-child(even) {background:var(--sw-bg);}
    .sw-footer {border-top:1px solid var(--sw-line);margin-top:28px;padding-top:16px;font-size:11px;color:var(--sw-muted);}
    @media(max-width:800px){.block-container{padding:1rem}.hero h1{font-size:28px}.st-key-main_nav [role="radiogroup"]>label{padding:7px 10px}[data-testid="stMetricValue"]{font-size:25px}}
    @media(prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important;}}
    '''
    for k,v in p.items(): css=css.replace(k.upper(),v)
    css=css.replace('PAD','14px' if compact else '20px')
    st.html('<style>' + css + '</style>')

def hero(title,description):
    st.html(f"""<section class="hero"><div class="eyebrow">Business workspace / {escape(st.session_state.get('main_nav', 'Executive'))}</div><h1>{escape(title)}</h1><p>{escape(description)}</p></section>""")

def context(*labels):
    st.html('<div class="sw-context">' + ''.join((f'<span class="sw-chip">{escape(str(x))}</span>' for x in labels)) + '</div>')

def insight(text):
    if st.session_state.get('guided_mode',True):
        st.html(f'<div class="insight"><b>WHAT THIS TELLS YOU</b>{escape(text)}</div>')

def plot(fig,height=340):
    p=palette()
    if st.session_state.get('compact_mode'): height=max(260,height-50)
    fig.update_layout(template='plotly_dark' if st.session_state.get('dark_mode') else 'plotly_white',height=height,
        paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',font=dict(family='Arial, sans-serif',color=p['muted'],size=12),
        margin=dict(l=10,r=15,t=20,b=35),colorway=COLORS,legend=dict(orientation='h',y=-.22,x=0),
        hoverlabel=dict(bgcolor=p['surface'],font_color=p['text'],bordercolor=p['line']))
    fig.update_xaxes(showgrid=False,zerolinecolor=p['line'],automargin=True)
    fig.update_yaxes(gridcolor=p['line'],zerolinecolor=p['line'],automargin=True)
    if not st.session_state.get('chart_labels',True):
        for trace in fig.data:
            if trace.type=='pie': trace.textinfo='none'
            elif trace.type=='bar': trace.textposition='none'
            elif hasattr(trace,'text'): trace.text=None
    st.plotly_chart(fig,width='stretch',theme=None,config={'displaylogo':False,'modeBarButtonsToRemove':['lasso2d','select2d']})

def bars(frame,category,value,title,color=None):
    with st.container(border=True):
        st.subheader(title)
        fig=px.bar(frame,x=value,y=category,orientation='h',color=color,color_discrete_sequence=COLORS,
                   color_discrete_map=STATUS_COLORS if color=='stock_status' else None,labels={value:'',category:''})
        fig.update_yaxes(categoryorder='total ascending')
        fig.update_traces(marker_line_width=0,hovertemplate='%{y}<br>%{x:,.2f}<extra></extra>')
        plot(fig)

def details(frame,title='Explore the records',filename='stridewell.csv'):
    with st.expander(title):
        term=st.text_input('Search these records',key=filename+'_search',placeholder='Type a store, product, or reason…')
        data=frame
        if term: data=frame[frame.astype(str).apply(lambda c:c.str.contains(term,case=False,regex=False)).any(axis=1)]
        st.caption(f'{len(data):,} matching records · exports include all matching records in this loaded view')
        count=max(1,math.ceil(len(data)/25))
        page=st.selectbox('Table page',range(1,count+1),key=filename+'_page')
        display=data.iloc[(page-1)*25:page*25].rename(columns=lambda c:c.replace('_',' ').capitalize())
        st.html('<div class="sw-table-wrap">' + display.to_html(index=False, escape=True, classes='sw-table', border=0, na_rep='—', float_format=lambda x: f'{x:,.2f}') + '</div>')
        st.download_button('↓ Download filtered CSV',data.to_csv(index=False).encode(),filename,'text/csv',key=filename+'_download')
