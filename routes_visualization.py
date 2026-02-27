import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from shapely import wkt
from shapely.geometry import Point
from shapely import from_wkb
from pyproj import Geod

# ----------------------------
# Params
# ----------------------------
species = 'norwhe'
resolution = 3
pathfinding_method = 'fw_vg'
elevation_limit = 0

st.set_page_config(layout="wide", page_title="H3 Route Explorer")

# ----------------------------
# Utils
# ----------------------------
geod = Geod(ellps="WGS84")

def interpolate_geodesic(path, num_points=10):
    lat1, lon1 = path[0][0], path[0][1]
    lat2, lon2 = path[1][0], path[1][1]
    pts = geod.npts(lon1, lat1, lon2, lat2, num_points, initial_idx=0, terminus_idx=0)
    return [[lat, lon] for lon, lat in pts]

# ----------------------------
# Load data (all cached)
# ----------------------------
@st.cache_data
def load_barriers():
    with open(f'{species}/resolution_{resolution}/tables/barrier.wkb', 'rb') as f:
        b = from_wkb(f.read())
    return b.__geo_interface__

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

@st.cache_data
def get_departure_cells(_gdf):
    return set(_gdf.loc[_gdf["value_wintering"] > 0, "cell"])

@st.cache_data
def get_destination_cells(_gdf):
    return set(_gdf.loc[_gdf["value_breeding"] > 0, "cell"])

barriers_geo = load_barriers()
df = load_cells()
routes_idx = load_routes()
cells_json = cells_geojson(df)
departure_cells = get_departure_cells(df)
destination_cells = get_destination_cells(df)

# ----------------------------
# Session state
# ----------------------------
if "origin" not in st.session_state:
    st.session_state.origin = None
if "target" not in st.session_state:
    st.session_state.target = None

# ----------------------------
# Styling
# ----------------------------
st.markdown("""
    <style>
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }
    .stButton button { width: 100%; }
    </style>
""", unsafe_allow_html=True)

# ----------------------------
# Header
# ----------------------------
st.title("H3 Route Explorer")

c1, c2, c3, c4 = st.columns([3, 3, 1, 2])
with c1:
    st.markdown(f"🟢 **Origin:** `{st.session_state.origin or 'none'}`")
with c2:
    st.markdown(f"🔴 **Target:** `{st.session_state.target or 'none'}`")
with c3:
    if st.button("Reset"):
        st.session_state.origin = None
        st.session_state.target = None
        st.rerun()
with c4:
    show_grid = st.checkbox("Show H3 grid", value=True)

# ----------------------------
# Build map
# ----------------------------
center = [df["lat"].mean(), df["lng"].mean()]
m = folium.Map(location=center, zoom_start=3, tiles="cartodbpositron")

# H3 grid (optional)
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

# Barriers (single GeoJson call for whole multipolygon)
folium.GeoJson(
    barriers_geo,
    style_function=lambda x: {
        "fillColor": "red",
        "color": "red",
        "weight": 2,
        "fillOpacity": 0.35,
    },
).add_to(m)

# Selected cells
def draw_h3(cell, color):
    geom = df.loc[df["cell"] == cell, "geometry"]
    if not geom.empty:
        folium.GeoJson(
            geom.iloc[0].__geo_interface__,
            style_function=lambda x, c=color: {
                "fillColor": c,
                "color": c,
                "weight": 2,
                "fillOpacity": 0.6,
            },
        ).add_to(m)

if st.session_state.origin:
    draw_h3(st.session_state.origin, "green")
if st.session_state.target:
    draw_h3(st.session_state.target, "red")

# Route
route_row = None
if st.session_state.origin and st.session_state.target:
    key = (st.session_state.origin, st.session_state.target)
    if key in routes_idx.index:
        route_row = routes_idx.loc[key]
        path = route_row["path"]
        smoothed = []
        for i in range(len(path) - 1):
            smoothed.extend(interpolate_geodesic([path[i], path[i + 1]], num_points=10))
        smoothed.append(path[-1])
        folium.PolyLine(smoothed, weight=4, color="royalblue").add_to(m)

# ----------------------------
# Render map
# ----------------------------
map_data = st_folium(
    m,
    width=1300,
    height=500,
    returned_objects=["last_clicked"],
)

# ----------------------------
# Handle click
# ----------------------------
if map_data.get("last_clicked"):
    lat = map_data["last_clicked"]["lat"]
    lon = map_data["last_clicked"]["lng"]
    point = Point(lon, lat)

    idx = list(df.sindex.intersection(point.bounds))
    candidates = df.iloc[idx]
    hit = candidates[candidates.geometry.contains(point)]

    if not hit.empty:
        cell = hit.iloc[0]["cell"]

        if st.session_state.origin is None:
            if cell in departure_cells:
                st.session_state.origin = cell
                st.rerun()
            else:
                st.warning("Not a valid departure cell.")

        elif st.session_state.target is None:
            if cell in destination_cells:
                st.session_state.target = cell
                st.rerun()
            else:
                st.warning("Not a valid destination cell.")

# ----------------------------
# Route details
# ----------------------------
st.markdown("---")
st.subheader("Route details")

if route_row is not None:
    st.dataframe(route_row.to_frame().T)
else:
    st.info("Click a departure cell (wintering) then a destination cell (breeding) to see the route.")