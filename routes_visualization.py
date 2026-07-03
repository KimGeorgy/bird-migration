import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from shapely import wkt
from shapely.geometry import box, shape, Point, LineString, MultiPolygon, Polygon
from shapely.validation import make_valid
from shapely import from_wkb
from pyproj import Geod
import antimeridian

# ----------------------------
# Params
# ----------------------------
species = 'norwhe'
resolution = 3
pathfinding_method = 'fw_vg'
elevation_limit = 3000
pseudocounts_fraction = 0.1
DEPARTURE_VALUE = 'value_breeding'
DESTINATION_VALUE = 'value_wintering'

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

def densify_polygon(poly, num_pts=10):
    def fix_ring(ring):
        coords = list(ring.coords)
        new_coords = []
        for i in range(len(coords) - 1):
            # Get geodesic points
            segment = interpolate_geodesic([coords[i][::-1], coords[i+1][::-1]], num_points=num_pts)
            # Add all points EXCEPT the last one of the segment 
            # (to avoid duplicating it with the start of the next segment)
            new_coords.extend([(p[1], p[0]) for p in segment[:-1]])
        
        # Add the very last point to close the ring
        new_coords.append(coords[-1])
        return new_coords

    if poly.geom_type == 'Polygon':
        return Polygon(fix_ring(poly.exterior), [fix_ring(h) for h in poly.interiors])
    elif poly.geom_type == 'MultiPolygon':
        return MultiPolygon([densify_polygon(p, num_pts) for p in poly.geoms])
    return poly
    
# ----------------------------
# Load data (all cached)
# ----------------------------
# @st.cache_data
# def load_barriers():
#     with open(f'{species}/resolution_{resolution}/tables/barrier.wkb', 'rb') as f:
#         barrier_geom = from_wkb(f.read())
    
#     # 1. Create a giant box representing the whole world
#     # Coordinates: [min_lon, min_lat, max_lon, max_lat]
#     world_box = box(-180, -90, 180, 90)
    
#     # 2. Subtract the barrier from the world
#     # This creates a polygon with "holes" where the barriers used to be
#     inverted_barrier = world_box.difference(barrier_geom)
    
#     # 3. Use antimeridian to ensure the giant world-polygon doesn't glitch
#     import antimeridian
#     fixed_inverted = antimeridian.fix_shape(inverted_barrier)
    
#     return fixed_inverted # Return the geometry (Folium handles the interface)
@st.cache_data
def load_barriers():
    with open(f'{species}/resolution_{resolution}/tables/barrier.wkb', 'rb') as f:
        barrier_geom = from_wkb(f.read())
    
    # 1. Densify with the 'no-duplicate' logic
    densified = densify_polygon(barrier_geom, num_pts=10)
    
    # 2. Fix topology BEFORE the difference
    # We use a tiny buffer (0.00001) instead of 0 to "weld" nearby points 
    # created by the geodesic math
    clean_barrier = densified.buffer(0.00001)

    # 3. Old Rendering: The Difference
    from shapely.geometry import box
    world_box = box(-180, -90, 180, 90)
    inverted_barrier = world_box.difference(clean_barrier)
    
    # 4. Antimeridian fix (the source of the "lol" lines)
    import antimeridian
    fixed = antimeridian.fix_shape(inverted_barrier)
    
    if isinstance(fixed, dict):
        from shapely.geometry import shape
        return shape(fixed)
    return fixed

@st.cache_data
def load_cells():
    df = pd.read_csv(f'{species}/resolution_{resolution}/tables/h3_abundance_{pseudocounts_fraction}.csv')
    # 1. Load initial WKT to Shapely
    df["geometry"] = df["geometry"].apply(wkt.loads)
    
    import antimeridian
    def fix_and_convert(g):
        # 2. Fix the antimeridian crossing
        fixed = antimeridian.fix_shape(g)
        # 3. CRITICAL: If 'fixed' is a dict, turn it back into a Shapely object
        if isinstance(fixed, dict):
            return shape(fixed)
        return fixed

    df["geometry"] = df["geometry"].apply(fix_and_convert)
    
    # Now GeoPandas will be happy because df["geometry"] contains Shapely objects
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
    return set(_gdf.loc[_gdf[DEPARTURE_VALUE] > 0, "cell"])

@st.cache_data
def get_destination_cells(_gdf):
    return set(_gdf.loc[_gdf[DESTINATION_VALUE] > 0, "cell"])

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

c1, c2, c3, c4, c5 = st.columns([3, 3, 2, 2, 1])
with c1:
    origin_input = st.text_input("🟢 Origin cell", value=st.session_state.origin or "", placeholder="e.g. 831f1afffffffff")
with c2:
    target_input = st.text_input("🔴 Target cell", value=st.session_state.target or "", placeholder="e.g. 831f1afffffffff")
with c3:
    st.markdown("<div style='margin-top:28px'/>", unsafe_allow_html=True)
    if st.button("Apply", use_container_width=True):
        origin_val = origin_input.strip() or None
        target_val = target_input.strip() or None

        error = False
        if origin_val and origin_val not in departure_cells:
            st.warning("Origin is not a valid departure cell.")
            error = True
        if target_val and target_val not in destination_cells:
            st.warning("Target is not a valid destination cell.")
            error = True

        if not error:
            st.session_state.origin = origin_val
            st.session_state.target = target_val
            st.rerun()
with c4:
    st.markdown("<div style='margin-top:28px'/>", unsafe_allow_html=True)
    if st.button("Reset", use_container_width=True):
        st.session_state.origin = None
        st.session_state.target = None
        st.rerun()
with c5:
    st.markdown("<div style='margin-top:28px'/>", unsafe_allow_html=True)
    show_grid = st.checkbox("Grid", value=True)

# ----------------------------
# Build map
# ----------------------------
center = [df["lat"].mean(), df["lng"].mean()]
m = folium.Map(location=center, zoom_start=2, tiles="cartodbpositron")

# H3 grid (optional)
if show_grid:
    folium.GeoJson(
        df[["cell", "geometry"]], # Pass the GDF directly
        style_function=lambda x: {
            "fillColor": "wheat",
            "color": "tan",
            "weight": 0.3,
            "fillOpacity": 0.3,
        },
        tooltip=folium.GeoJsonTooltip(fields=["cell"]),
    ).add_to(m)

# Barriers
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
        import antimeridian
        # Use fix_shape on the polygon geometry
        fixed_cell = antimeridian.fix_shape(geom.iloc[0])
        
        folium.GeoJson(
            fixed_cell,
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

# ----------------------------
# Route
# ----------------------------
route_row = None
if st.session_state.origin and st.session_state.target:
    key = (st.session_state.origin, st.session_state.target)
    if key in routes_idx.index:
        route_row = routes_idx.loc[key]
        path = route_row["path"]
        
        # 1. Your original interpolation logic
        smoothed = []
        for i in range(len(path) - 1):
            smoothed.extend(interpolate_geodesic([path[i], path[i + 1]], num_points=10))
        smoothed.append(path[-1])
        
        # 2. Convert to (Lon, Lat) for Shapely/Antimeridian
        path_lon_lat = [(p[1], p[0]) for p in smoothed]
        line = LineString(path_lon_lat)
        
        # 3. Fix the antimeridian crossing
        import antimeridian
        fixed_shape = antimeridian.fix_shape(line)
        
        # 4. Render to map
        # Passing fixed_shape directly (works for both dict and shapely types)
        folium.GeoJson(
            fixed_shape,
            style_function=lambda x: {
                "color": "royalblue",
                "weight": 4,
                "opacity": 0.8
            }
        ).add_to(m)

# ----------------------------
# Render map
# ----------------------------
map_data = st_folium(
    m,
    use_container_width=True, # Automatically takes up the full width
    height=750,               # Increased from 500
    returned_objects=["last_clicked"],
)

# ----------------------------
# Handle map click (original behavior)
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
    st.info("Select a departure cell and destination cell to see the route.")