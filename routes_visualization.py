import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from shapely import wkt
from shapely.geometry import Polygon, Point

# ----------------------------
# Params
# ----------------------------
species = 'amewoo'
resolution = 3
pathfinding_method = 'fw_vg'
elevation_limit = 2000

st.set_page_config(layout="wide")

# ----------------------------
# Utils
# ----------------------------
def swap_coords(coords):
    return [(lon, lat) for lat, lon in coords]

# ----------------------------
# Barriers
# ----------------------------
boundaries = [
    [(40, -81), (43, -85), (40, -80), (39, -80), (39, -90), (40, -90)],
    [(41, -87), (43, -89), (43, -90)]
]
barriers = [Polygon(swap_coords(b)) for b in boundaries]

# ----------------------------
# Load data (cached)
# ----------------------------
@st.cache_data
def load_cells():
    df = pd.read_csv(f'{species}/resolution_{resolution}/tables/h3_abundance.csv')
    df["geometry"] = df["geometry"].apply(wkt.loads)
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
    _ = gdf.sindex
    return gdf

@st.cache_data
def load_routes():
    df = pd.read_pickle(
        f'{species}/resolution_{resolution}/tables/'
        f'{species}_all_routes_{pathfinding_method}_{elevation_limit}.pkl'
    )
    return df.set_index(["departure_cell", "destination_cell"])

@st.cache_data
def cells_geojson(_gdf):
    return _gdf[["cell", "geometry"]].to_json()

df = load_cells()
routes_idx = load_routes()
cells_json = cells_geojson(df)

departure_cells = set(df.loc[df["value_wintering"] > 0, "cell"])
destination_cells = set(df.loc[df["value_breeding"] > 0, "cell"])

# ----------------------------
# Session state
# ----------------------------
if "origin" not in st.session_state:
    st.session_state.origin = None
if "target" not in st.session_state:
    st.session_state.target = None

# ============================
# UI TOP (single screen)
# ============================

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1rem;   /* уменьшает верхний отступ */
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("H3 Route Explorer")

c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
with c1:
    st.markdown(f"🟢 **Origin:** `{st.session_state.origin}`")
with c2:
    st.markdown(f"🔴 **Target:** `{st.session_state.target}`")
with c3:
    if st.button("Reset"):
        st.session_state.origin = None
        st.session_state.target = None
        st.rerun()
with c4:
    show_grid = st.checkbox("Show H3 grid", value=True)

# ============================
# Build map
# ============================
center = [df["lat"].mean(), df["lng"].mean()]
m = folium.Map(location=center, zoom_start=5, tiles="cartodbpositron")

# --- draw ALL H3 cells as background (optional toggle)
if show_grid:
    folium.GeoJson(
        cells_json,
        style_function=lambda x: {
            "fillColor": "wheat",
            "color": "tan",
            "weight": 0.3,
            "fillOpacity": 0.3,
        },
        tooltip=folium.GeoJsonTooltip(fields=["cell"]),
    ).add_to(m)

# --- draw barriers
for poly in barriers:
    folium.GeoJson(
        poly.__geo_interface__,
        style_function=lambda x: {
            "fillColor": "red",
            "color": "red",
            "weight": 2,
            "fillOpacity": 0.35,
        },
    ).add_to(m)

def draw_h3(cell, color):
    geom = df.loc[df["cell"] == cell, "geometry"]
    if not geom.empty:
        folium.GeoJson(
            geom.iloc[0].__geo_interface__,
            style_function=lambda x: {
                "fillColor": color,
                "color": color,
                "weight": 2,
                "fillOpacity": 0.6,
            },
        ).add_to(m)

# --- draw selected cells
if st.session_state.origin:
    draw_h3(st.session_state.origin, "green")
if st.session_state.target:
    draw_h3(st.session_state.target, "red")

# --- draw route
route_row = None
if st.session_state.origin and st.session_state.target:
    key = (st.session_state.origin, st.session_state.target)
    if key in routes_idx.index:
        route_row = routes_idx.loc[key]
        path = route_row["path"]
        folium.PolyLine(path, weight=4).add_to(m)

# ============================
# Render map (still in top screen)
# ============================
map_data = st_folium(m, width=1300, height=600)

# ============================
# Handle click (FAST)
# ============================
if map_data.get("last_clicked"):
    lat = map_data["last_clicked"]["lat"]
    lon = map_data["last_clicked"]["lng"]
    point = Point(lon, lat)

    idx = list(df.sindex.intersection(point.bounds))
    candidates = df.iloc[idx]
    hit = candidates[candidates.contains(point)]

    if not hit.empty:
        cell = hit.iloc[0]["cell"]

        if st.session_state.origin is None:
            if cell in departure_cells:
                st.session_state.origin = cell
                st.rerun()
            else:
                st.warning("Not a valid departure cell")

        elif st.session_state.target is None:
            if cell in destination_cells:
                st.session_state.target = cell
                st.rerun()
            else:
                st.warning("Not a valid destination cell")

# ============================
# Bottom: details / table
# ============================
bottom = st.container()
with bottom:
    st.markdown("---")
    st.subheader("Route details")

    if route_row is not None:
        st.dataframe(route_row.to_frame().T)
    else:
        st.info("Select origin and target cells to see route details.")
