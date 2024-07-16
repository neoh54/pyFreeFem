from pylab import *
import triangle as tr
import json as json
from scipy.sparse.linalg import spsolve
# from shapely.geometry import Polygon as shp_Polygon
from shapely import wkt as shp_wkt

'''
https://rufat.be/triangle/index.html
'''

with open('grains.json') as the_file :
    boundaries = json.load(the_file)


Ts = { 'segments' : [], 'vertices' : [], 'segment_markers' : [], 'holes' :[] }


for interior in shp_wkt.loads( boundaries['box'] ).interiors : # there is only one interior

    for point in interior.coords[:-1] :

        Ts['vertices'] += [ point ]

        try :
            vertex_index += 1
        except :
            vertex_index = 0

        if vertex_index > 0 :
            Ts['segments'] += [ [ vertex_index - 1, vertex_index ] ]

    Ts['segments'] += [ [ vertex_index, 0 ] ]

Ts['segment_markers'] = ( -arange( 1, 5 ) ).tolist()

shrink_factor = .99

for grain in boundaries['grains'] :

    points = []
    
    grain = shp_wkt.loads( grain )
    center = grain.centroid
    Ts['holes'] += [ [center.x, center.y] ]

    for point in grain.exterior.coords[:-1] :

        point = center.x + shrink_factor*( point[0] - center.x ), center.y + shrink_factor*( point[1] - center.y )
        
        points += [ point ]
        vertex_index += 1

        if len(points) > 1 :
            Ts['segments'] += [ [ vertex_index - 1, vertex_index ] ]
            Ts['segment_markers'] += [ -5 ]

    Ts['segments'] += [ [ vertex_index, vertex_index - len(points) + 1 ] ]
    Ts['segment_markers'] += [ -5 ]

    Ts['vertices'] += points

###################
#
# Check
#
###################

# print(len(Ts['vertices']))


# for vertex in Ts['vertices'] :
#     plot(*vertex, 'ko')

# for hole in Ts['holes'] :
#     plot(*hole, '+m')

# for segment in Ts['segments'] :
#     plot( *array(Ts['vertices'])[segment].T, color = 'm'  )

# axis('scaled')

###################
#
# Build triangulation
#
###################

T = tr.triangulate( Ts, 'pa' )
# tr.compare( plt, Ts, T )


# savefig( 'compare.svg', bbox_inches = 'tight' )

####################
#
# pyFreefem mesh
#
####################


import sys
sys.path.append('./../../')

import pyFreeFem as pyff

Th = pyff.triangle_to_TriMesh( T )
Th.rename_boundary( { -1 :'bottom', -2:'side', -3:'top', -4:'side', -5:'grain' } )

boundary_number, boundary_name = Th.get_boundary_label_conversion()

Th = pyff.adaptmesh( Th, hmax = .1 )

####################
#
# pyFreefem matrix
#
####################

script = pyff.InputScript( Th = 'mesh' )
script += '''
fespace Vh( Th, P2 );
Vh u,v;
Vh X = x, Y = y;
'''
script += pyff.VarfScript(
    stiffness = 'int2d(Th)( dx(u)*dx(v) +  dy(u)*dy(v) )',
    top = 'int1d(Th,' + str( boundary_number['top'] ) + ')( u*v )',
    bottom = 'int1d(Th,' + str( boundary_number['bottom'] ) + ')( u*v )'
    )

script += pyff.OutputScript( X = 'vector', Y = 'vector' )

epsilon = 1e-6

for _ in range(3) :

    try :
        Th = pyff.adaptmesh( Th, c, hmin = 0.02 )
    except :
        pass
    
    FE_matrices = script.get_output( Th = Th )
    M = FE_matrices['stiffness'] - 1/epsilon*( FE_matrices['top'] + FE_matrices['bottom'] )
    B = FE_matrices['top']@( FE_matrices['X']*0 + 1 )
    c = spsolve( M, B )

p = pyff.get_projector( Th, 'P2', 'P1' )

figure()
tricontourf( Th, p@c )
tricontour( Th, p@c, colors = 'r', lw = .5, linestyles = '-' )

# Th.plot_triangles( color = 'w', alpha = .1, lw = .75)#( labels = 'label' )
# Th.plot_boundaries( label = 'grains', color = 'grey' )
# Th.plot_nodes( labels = 'label', color = 'tab:blue' )
# legend()

axis('equal')
axis('off')
# # savefig( 'river.svg', bbox_inches = 'tight' )

show()
