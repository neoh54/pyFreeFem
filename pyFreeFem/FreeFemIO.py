#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Olivier Devauchelle
#
# Many thanks to Eric Lajeunesse, Anaïs Abramian, Valentin Jules & Hugo Chauvet.
#
# When used in a scientific publication, please cite:
#
# Boltzmann Distribution of Sediment Transport, A. Abramian, O. Devauchelle,
# G. Seizilles, E. Lajeunesse, Physical Review Letters, 123, 014501, 2019

import numpy as np
import re
import csv
import subprocess
from scipy.sparse import csr_matrix
from tempfile import NamedTemporaryFile

from .TriMesh import TriMesh #, triangle_edge_to_node_edge
from .meshTools.segments import triangle_edge_to_node_edge
from .FreeFemTools.FreeFemStatics import *
from .FreeFemTools.edpTools import flagize

default_sparse_matrix = csr_matrix

def parse_FreeFem_output( FreeFem_str, flag ) :

    return FreeFem_str.split( flag + '\n' )[1]

def FreeFem_str_to_matrix( FreeFem_str, matrix_name = None, flag = None, sparse_matrix = None ) :
    '''
    '''

    if not flag is None :
        FreeFem_lines = parse_FreeFem_output( FreeFem_str, flag ).split('\n')

    elif not matrix_name is None:
        flag = flagize( matrix_name ) # '# MATRIX ' + matrix_name
        FreeFem_lines = parse_FreeFem_output( FreeFem_str, flag ).split('\n')

    else :
        FreeFem_lines = FreeFem_str.split('\n')

    nb_row, nb_col, is_symmetric, nb_coef = map( lambda x : int(x), FreeFem_lines[3].split() )
    I, J, coef = loadstr( '\n'.join(  FreeFem_lines[4:-1] ) ).T
    I = np.array( list( map( lambda x: int(x), I ) ) ) - 1
    J = np.array( list( map( lambda x: int(x), J ) ) ) - 1
    coef = np.array( list( map( lambda x: float(x), coef ) ) )

    if sparse_matrix is None :
        return default_sparse_matrix( ( coef, (I, J) ), ( nb_row, nb_col ) )

    elif sparse_matrix is 'raw' :
        return ( coef, (I, J) ), ( nb_row, nb_col )

    else :
        return sparse_matrix( ( coef, (I, J) ), ( nb_row, nb_col ) )

def FreeFem_str_to_vector( Freefem_str, dtype = 'float' ) :
    return  loadstr( Freefem_str[:-1], dtype = dtype ).flatten( )

def FreeFem_str_to_mesh( FreeFem_str ) :

    FreeFem_str = '\n' + FreeFem_str + '\n'

    FreeFem_mesh = {}

    for key in ['triangles', 'boundaries'] :
        FreeFem_mesh[key] = loadstr( FreeFem_str.split( '\n' + flagize(key) + '\n' )[1], dtype = 'int' )

    for key in ['nodes'] :
        FreeFem_mesh[key] = loadstr( FreeFem_str.split( '\n' + flagize(key) + '\n' )[1], dtype = 'float' )

    x, y, node_labels = FreeFem_mesh['nodes'].T
    node_labels = list( map( lambda x: int(x), node_labels ) )

    triangles = FreeFem_mesh['triangles'][:,:-1]
    triangle_labels = FreeFem_mesh['triangles'][:,-1]

    boundary_edges = {}

    for edge in FreeFem_mesh['boundaries'] :
        # print(edge)
        boundary_edges.update( FreeFem_edge_to_boundary_edge( edge, triangles ) )

    mesh = TriMesh(
        x, y,
        triangles = triangles,
        node_labels = node_labels,
        triangle_labels = triangle_labels,
        boundary_edges = boundary_edges
        )

    return mesh


def find_triangle_index( triangles, start_node, end_node ) :

    triangle_index = None

    for nodes_order in [ [0,1], [1,2], [-1,0] ] :
        try :
            triangle_index = triangles[ :, nodes_order].tolist().index( [ start_node, end_node ] )
            break
        except :
            pass

    return triangle_index



def FreeFem_edge_to_boundary_edge( FreeFem_edge, triangles, flip_reversed_edges = True ) :
    '''
    ( start_node, end_node, label_integer ) -> { ( triangle_index, triangle_node_index ) : label_integer }
    '''

    start_node, end_node, label_integer = FreeFem_edge

    triangle_index = find_triangle_index( triangles, start_node, end_node )

    if triangle_index is None and flip_reversed_edges:
        print('Reversing edge ' + str(FreeFem_edge) + '' )
        start_node, end_node = end_node, start_node
        triangle_index = find_triangle_index( triangles, start_node, end_node )

    if triangle_index is None :
        print('Could not find boundary edge ' + str(FreeFem_edge) + '' )
        return {}

    else :
        node_index_in_triangle = triangles[triangle_index].tolist().index( start_node )
        return { ( triangle_index, node_index_in_triangle ) : label_integer  }

def savemesh( mesh, filename ) :
    '''
    Saves mesh in FreeFem++ format in a .msh file.
    '''

    with open( filename, 'w' ) as the_file :

        # nv, nt, ne
        the_file.write( str( [ len( mesh.x), len( mesh.triangles ), len( mesh.boundary_edges ) ] )[1:-1].replace(',',' ') + '\n' )

        # vertices
        for node_index in range( len( mesh.x ) ) :
            the_file.write( str( mesh.x[node_index] ) + ' ' + str( mesh.y[node_index] ) + ' ' + str( mesh.node_labels[node_index] ) + '\n' )

        # triangles
        for tri_index, triangle in enumerate( mesh.triangles ) :
            the_file.write( str( list( np.array( triangle ) + 1 ) )[1:-1].replace(',',' ') + ' ' + str( mesh.triangle_labels[tri_index] ) + '\n' )

        # edges
        for edge in mesh.get_boundary_edges() :
            the_file.write( str( list( np.array( edge ) + np.array([ 1, 1, 0 ]) ) )[1:-1].replace(',',' ') + '\n' )

    return filename


def loadstr( data_str, delimiter = None, dtype = 'float', skip_rows = 0 ) :

    '''
    An approximation of np.loadtxt that applies to str.
    '''


    if dtype is 'float' :
        def conversion_try( x ) :
            return float( x )

    elif dtype is 'int' :
        def conversion_try( x ) :
            return int( x )

    else :
        def conversion_try( x ) :
            return x

    def conversion(x) :
        try :
            return conversion_try(x)
        except :
            return x

    data = []

    for data_line in data_str.split('\n')[skip_rows:] :
        data += [ list( map( conversion, data_line.split( delimiter ) ) ) ]

    return np.array(data)

def run_FreeFem( edp_str, verbose = False ) :
    '''
    Run FreeFem++ on script edp_str, and returns Popen output.
    '''

    edp_str = edp_str.replace( '"',  "\"'\"" )

    command = 'FreeFem++ -v 0 <( printf "' + edp_str + '" )'

    with subprocess.Popen( [command], stdout = subprocess.PIPE, stderr = subprocess.PIPE, shell = True, executable="/bin/bash" ) as proc :

        if verbose :
            print('\nRunning FreeFem++...')

        output, error = proc.communicate() # Freefem outputs errors in console

        if not proc.returncode :
            if verbose :
                print('\nFreeFem++ run successfull.\n')
            return output.decode('utf-8')

        else :
            print('\n-------------------')
            print('FreeFem++ error :')
            print('-------------------')
            print(output.decode('utf-8'))
            print('-------------------\n')

            if verbose :
                print('\n-------------------')
                print('edp file :')
                print('-------------------')
                for line_number, line in enumerate( edp_str.split('\n') ) :
                    print( str( line_number + 1 ) + '    ' + line )
                print('-------------------\n')

            return None


if __name__ == '__main__' :

    from pylab import *
    from scipy.sparse.linalg import spsolve

    edp_str = '''
    real smallRadius = .3;
    border outerCircle( t = 0, 2*pi ){ x = cos(t); y = 0.8*sin(t); }
    border innerCircle( t = 2*pi, 0 ){ x = .5 + smallRadius*cos(t); y = smallRadius*sin(t); }
    mesh Th = buildmesh( outerCircle(100) + innerCircle(40) );

    fespace Vh( Th, P1 );
    Vh u,v;
    '''

    edp_str += export_mesh_edp()

    matrix_types = [ stiffness, Grammian, boundary_Grammian(1,2) ]

    for matrix_type in matrix_types :
        edp_str += export_matrix_edp( **matrix_type )

    FreeFem_output = run_FreeFem( edp_str )

    # print(FreeFem_output)

    mesh = FreeFem_str_to_mesh( FreeFem_output  )

    matrices = {}

    for matrix_type in matrix_types :
        matrices[ matrix_type['matrix_name'] ] = FreeFem_str_to_matrix( FreeFem_output, matrix_type['matrix_name'] )

    for matrix_type in matrix_types :
        print( matrix_type['matrix_name'] )

    epsilon = 1e-4
    M = - matrices[ stiffness['matrix_name'] ] + 1./epsilon*matrices[ boundary_Grammian(1,2)['matrix_name'] ]
    Source = matrices[ Grammian['matrix_name'] ]*np.array( [1]*len( mesh.x ) )
    u = spsolve( M, Source )

    tricontourf( mesh, u )
    # mesh_color =  the_mesh.plot_triangles( triangle_labels = False, alpha = .5 )[0].get_color()
    mesh.plot_boundaries( lw = 2, labels = False )
    # the_mesh.plot_nodes( )

    axis('equal')
    axis('off')

    show()
