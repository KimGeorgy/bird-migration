import streamlit as st
import pandas as pd
import geopandas as gpd
import plotly.express as px
import plotly.graph_objects as go
from shapely import wkt
from shapely.geometry import box, shape, Point, LineString, MultiPolygon, Polygon
from shapely import from_wkb
from pyproj import Geod
import antimeridian
import json

# ----------------------------
# Params & Config
# ----------------------------
species = 'norwhe'
resolution = 3
pathfinding_method = 'fw_vg'
elevation_limit = 3000
pseudocounts_fraction = 0.1
DEPARTURE_VALUE = 'value_breeding'
DESTINATION_VALUE = 'value_wintering'

st.set_page_config(layout="wide", page_title="H3 Route Explorer (Plotly)")

# ----------------------------
# Utils
# ----------------------------
geod = Geod(ellps="WGS84")

def interpolate_geodesic(path, num_points=10):
    lat1, lon1 = path[0][0], path[0][1]
    lat2, lon2 = path[1][0], path[1][1]
    pts = geod.npts(lon1, lat1, lon2, lat2, num_points, initial_idx=0, terminus_idx=0)
    return [[lat, lon] for lon, lat in pts]

def densify_polygon(poly, num_pts=10):
    def fix_ring(ring):
        coords = list(ring.coords)
        new_coords = []
        for i in range(len(coords) - 1):
            segment = interpolate_geodesic([coords[i][::-1], coords[i+1][::-1]], num_points=num_pts)
            new_coords.extend([(p[1], p[0]) for p in segment[:-1]])
        new_coords.append(coords[-1])
        return new_coords

    if poly.geom_type == 'Polygon':
        return Polygon(fix_ring(poly.exterior), [fix_ring(h) for h in poly.interiors])
    elif poly.geom_type == 'MultiPolygon':
        return MultiPolygon([densify_polygon(p, num_pts) for p in poly.geoms])
    return poly

# ----------------------------
# Load data
# ----------------------------
@st.cache_data
def load_barriers():
    with open(f'{species}/resolution_{resolution}/tables/barrier.wkb', 'rb') as f:
        barrier_geom = from_wkb(f.read())
    densified = densify_polygon(barrier_geom, num_pts=10)
    clean_barrier = densified.buffer(0.00001)
    world_box = box(-180, -90, 180, 90)
    inverted_barrier = world_box.difference(clean_barrier)
    fixed = antimeridian.fix_shape(inverted_barrier)
    return shape(fixed) if isinstance(fixed, dict) else fixed

@st.cache_data
def load_cells():
    df = pd.read_csv(f'{species}/resolution_{resolution}/tables/h3_abundance_{pseudocounts_fraction}.csv')
    df["geometry"] = df["geometry"].apply(lambda g: shape(antimeridian.fix_shape(wkt.loads(g))))
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
    gdf['id'] = gdf['cell'] # Plotly needs an explicit ID for choropleth
    return gdf

@st.cache_data
def load_routes():
    df = pd.read_pickle(f'{species}/resolution_{resolution}/tables/{species}_all_routes_{pathfinding_method}_{elevation_limit}.pkl')
    return df.set_index(["departure_cell", "destination_cell"])

# Init Data
barriers_geo = load_barriers()
gdf = load_cells()
routes_idx = load_routes()
departure_cells = set(gdf.loc[gdf[DEPARTURE_VALUE] > 0, "cell"])
destination_cells = set(gdf.loc[gdf[DESTINATION_VALUE] > 0, "cell"])

# ----------------------------
# Session state
# ----------------------------
if "origin" not in st.session_state: st.session_state.origin = None
if "target" not in st.session_state: st.session_state.target = None

# ----------------------------
# Header & Controls
# ----------------------------
st.title("H3 Route Explorer (Plotly)")

c1, c2, c3, c4, c5 = st.columns([3, 3, 2, 2, 1])
with c1:
    origin_input = st.text_input("🟢 Origin", value=st.session_state.origin or "")
with c2:
    target_input = st.text_input("🔴 Target", value=st.session_state.target or "")
with c3:
    st.markdown("<div style='margin-top:28px'/>", unsafe_allow_html=True)
    if st.button("Apply"):
        st.session_state.origin = origin_input if origin_input in departure_cells else None
        st.session_state.target = target_input if target_input in destination_cells else None
        st.rerun()
with c4:
    st.markdown("<div style='margin-top:28px'/>", unsafe_allow_html=True)
    if st.button("Reset"):
        st.session_state.origin = st.session_state.target = None
        st.rerun()
with c5:
    st.markdown("<div style='margin-top:28px'/>", unsafe_allow_html=True)
    show_grid = st.checkbox("Grid", value=True)

# ----------------------------
# Build Plotly Map
# ----------------------------
fig = go.Figure()

# 1. Base Grid (Choropleth for performance)
if show_grid:
    fig.add_trace(go.Choroplethmapbox(
        geojson=gdf.__geo_interface__,
        locations=gdf['id'],
        z=[1]*len(gdf),
        colorscale=[[0, 'wheat'], [1, 'wheat']],
        marker_opacity=0.3,
        marker_line_width=0.3,
        marker_line_color="tan",
        showscale=False,
        hoverinfo="text",
        text=gdf['cell'],
        name="H3 Grid"
    ))

# 2. Barriers
barrier_json = gpd.GeoSeries([barriers_geo]).__geo_interface__
fig.add_trace(go.Choroplethmapbox(
    geojson=barrier_json,
    locations=[0],
    z=[1],
    colorscale=[[0, 'red'], [1, 'red']],
    marker_opacity=0.35,
    marker_line_width=2,
    showscale=False,
    name="Barriers"
))

# 3. Origin/Target Highlighting
for cell, color, name in [(st.session_state.origin, "green", "Origin"), (st.session_state.target, "red", "Target")]:
    if cell:
        cell_geom = gdf[gdf['cell'] == cell].__geo_interface__
        fig.add_trace(go.Choroplethmapbox(
            geojson=cell_geom,
            locations=[cell],
            z=[1],
            colorscale=[[0, color], [1, color]],
            marker_opacity=0.8,
            showscale=False,
            name=name
        ))

# 4. Route Line
route_row = None
if st.session_state.origin and st.session_state.target:
    key = (st.session_state.origin, st.session_state.target)
    if key in routes_idx.index:
        route_row = routes_idx.loc[key]
        path = route_row["path"]
        
        # Geodesic smoothing
        smoothed = []
        for i in range(len(path) - 1):
            smoothed.extend(interpolate_geodesic([path[i], path[i + 1]], num_points=10))
        smoothed.append(path[-1])
        
        lats, lons = zip(*smoothed)
        
        fig.add_trace(go.Scattermapbox(
            lat=lats, lon=lons,
            mode='lines',
            line=dict(width=4, color='royalblue'),
            name="Route"
        ))

# Map Layout
fig.update_layout(
    mapbox_style="carto-positron",
    mapbox_zoom=2,
    mapbox_center={"lat": gdf["lat"].mean(), "lon": gdf["lng"].mean()},
    margin={"r":0,"t":0,"l":0,"b":0},
    height=750,
    clickmode='event+select'
)

# ----------------------------
# Render & Handle Interaction
# ----------------------------
# In newer Streamlit, we can capture the click directly from the component
selected_data = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points")

if selected_data and "selection" in selected_data and selected_data["selection"]["points"]:
    # Plotly returns the index of the point/polygon clicked
    point_index = selected_data["selection"]["points"][0]["point_index"]
    cell_id = gdf.iloc[point_index]["cell"]
    
    if st.session_state.origin is None:
        if cell_id in departure_cells:
            st.session_state.origin = cell_id
            st.rerun()
    elif st.session_state.target is None:
        if cell_id in destination_cells:
            st.session_state.target = cell_id
            st.rerun()

# Route Details
st.markdown("---")
if route_row is not None:
    st.dataframe(route_row.to_frame().T)
else:
    st.info("Click the map or enter IDs to explore routes.")