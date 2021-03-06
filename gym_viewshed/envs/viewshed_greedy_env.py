"""
Created on Mon Feb  3 13:41:56 2020

@author: Daulet Baimukashev
"""
import numpy as np
from PIL import Image
import cv2
import time
import arcpy
from arcpy import env
from arcpy.sa import Viewshed2
#from arcpy.da import *
import gym
from gym import error, spaces, utils
from gym.utils import seeding
import matplotlib.pyplot as plt
import math
import random

env.scratchWorkspace = r"in_memory"
print(arcpy.ClearWorkspaceCache_management())
env.overwriteOutput = True
env.outputCoordinateSystem = arcpy.SpatialReference("WGS 1984 UTM Zone 18N")
env.geographicTransformations = "Arc_1950_To_WGS_1984_5; PSAD_1956_To_WGS_1984_6"
#env.parallelProcessingFactor = "200%"
env.processorType = "GPU"
env.gpuID = "0"
env.compression = "LZ77" #"LZ77" #"JPEG" # LZW
env.tileSize = "128 128"
env.pyramid = "PYRAMIDS -1 CUBIC LZ77 NO_SKIP"

class ViewshedGreedyEnv(gym.Env):
    """
    Description:
        Viewshed analysis on raster data

    Source:
        ArcGIS function

    Observation:
        Type: Image

    Actions:
        Type: Discrete
        Num Action
        0   Rotate +5 deg
        1   Rotate -5 deg
        2   Move +5 pixel x
        3   Move -5 pixel x
        4   Move +5 pixel y
        5   Move -5 pixel y

    Reward:
        Reward 1 for game over

    Starting State:
        Init image of the city

    Episode termination:
        Episode > 100

    """
    metadata = {'render.modes': ['human']}

    def __init__(self):

        #input Raster
        self.city_array = np.array((Image.open(r"../data/images/total_city3_nearest_uint8_scale.png").convert('L')), dtype=np.uint8)  #.resize((900,600))
        self.non_zero_mask = np.array((Image.open(r"../data/images/nonZeroMask3_nearest_uint8_scale.png").convert('L')), dtype=np.uint8)
        self.im_height, self.im_width  = self.city_array.shape
        print(self.im_height)
        self.input_raster = arcpy.NumPyArrayToRaster(self.city_array)
        # input shapefile
        self.shape_file = r"../data/input_shapefile/1/points_XYTableToPoint_second.shp"
        # observer params
        self.camera_number = 1
        # camera locations
        self.a = int(self.im_width/35)*np.repeat(np.arange(self.camera_number ),3)

        self.aP = np.array([1809,1397,39,2573,1999,39,1684,2420,39,2255,2049,65,2132,3250,39,2594,2886,74,2559,3119,39,2247,1609,153,1942,849,39,3086,2116,39,2834,2019,39,2867,744,110,1392,832,39,758,1678,39,1333,1100,39,1878,1490,39,1957,765,39,2201,3167,86,456,862,53,2481,836,53,1673,3021,53,2612,2592,99,2210,2000,124,1952,1763,39,1324,2157,39,2853,2049,39,2697,2752,39,2504,1430,47,2936,2335,39,1836,192,39])

        self.observer_locations = np.zeros((self.camera_number,3))
        self.observer_locations_init = self.a.reshape(self.camera_number,3)   #10*np.zeros((10,3))
        #self.observer_locations[:,1] = 20
        # viewshed params
        self.analysis_type = "FREQUENCY"
        self.analysis_method = "PERIMETER_SIGHTLINES"
        self.outer_radius = 375
        self.inner_radius = 0
        self.radius_is_3d = 'True'
        self.observer_height = 0
        self.vertical_lower_angle  = -90
        self.vertical_upper_angle = 90
        # init params
        self.init_x = 1#int(self.im_width/10)
        self.init_y = 1#int(self.im_height/10)
        self.init_observer_dist = 1 # how far init observer from each other
        self.init_azimuth1 = 0
        self.init_azimuth2 = 360
        # info extra about the env
        self.info = 0.0  # ratio
        self.iteration = 0
        self.state = np.zeros((self.im_height, self.im_width))
        self.state_points = np.zeros((self.im_height, self.im_width))
        self.state_points_index = np.zeros((90000, 2))
        self.observer_viewpoint = np.zeros((self.im_height, self.im_width), dtype = np.uint8)
        # search parameter
        self.radius = 3
        self.radius_delta = 3
        self.move_step = 1
        self.min_height = 30
        # rendering
        self.is_render = 'True'
        self.max_render = 100
        self.imshow_dt = 0
        self.seed(0)
        print('init ViewshedRandomEnv successfully!')

    def seed(self, seed = None):
        self.np_random, seed = seeding.np_random()
        return [seed]

    def reset(self):
        #self.reset_shapefile(self.shape_file)
        self.state = np.zeros((self.im_height, self.im_width))
        self.iteration = 0
        return self.state

    def reset_shapefile(self, shape_file):

        #print('Reset init camera locations')
        fieldlist=['AZIMUTH1','AZIMUTH2','OFFSETA','RADIUS2']
        tokens=['SHAPE@X','SHAPE@Y']
        with arcpy.da.UpdateCursor(shape_file,tokens+fieldlist) as cursor:
            delta = -1
            X = self.init_observer_dist
            for row in cursor:
                delta += 1
                row[0]= self.init_x + (delta%self.camera_number)*X
                row[1]= self.init_y + (delta//self.camera_number)*X
                row[2]= self.init_azimuth1
                row[3]= self.init_azimuth2
                x = row[0]
                y = row[1]
                p = str(x) + " " + str(y)
                p_value = arcpy.GetCellValue_management(self.input_raster, p)
                row[4] = int(p_value[0])
                row[5]= self.outer_radius
                cursor.updateRow(row)
        del cursor

    def render(self, mode='human'):
        # to show
        if self.is_render == 'True' and self.iteration < self.max_render :
            print('render --- ratio --- ', self.info)
            self.show_image(self.state, self.imshow_dt)

    def close(self):
        pass

    def show_image(self,show_array,dt):

        show_array = show_array*50
        #show_array = Image.fromarray(show_array, 'L')
        #show_array = np.array(show_array)
        #show_array = cv2.resize(show_array, (800,800), interpolation = cv2.INTER_AREA)
        cv2.imwrite(r"../data/images/greedy_valid_points.png", show_array );
        cv2.startWindowThread()
        cv2.namedWindow("preview")
        cv2.imshow("preview", show_array)
        cv2.waitKey(dt & 0xFF)
        cv2.destroyAllWindows()

    ### STEP
    def step(self):

        self.iteration = self.iteration + 1

        self.move_to_valid_points()

        # move all observer to closest point
        #self.moveto_closest_point()
        #print('after move')
        #print(self.observer_locations)
        #print(self.observer_locations_init)
        # update shapefile
        self.update_shapefile_random(self.shape_file, self.observer_locations)
        # create the viewshed
        output_array, ratio = self.create_viewshed(self.input_raster, self.shape_file)

        # for rendering
        self.state = output_array
        self.info = ratio

        #self.state = self.state_points
        #print('-------')
        #print(np.sum(self.state))
        #print(np.sum(self.state_points))
        #self.info = 0.0

    def find_valid_points(self):

        arr = self.city_array
        y = self.im_height
        x = self.im_width
        print(x,y)
        count = 0

        for j in range(y):
            for i in range(x):
                if arr[j,i] > 50:
                    #print(j)
                    nb = self.get_spiral(j,i,1,1)
                    hi,wi = nb.shape
                    sum_nb = 0 # find the sum of zero neighbours
                    #print(nb)
                    for k in range(hi):
                        # FOR EACH NEIGHBOUR OF THE POINT:
                        y_nb = nb[k][0]
                        x_nb = nb[k][1]
                        if self.city_array[y_nb, x_nb] < 3:
                            sum_nb = sum_nb + 1

                    if sum_nb > 6:
                        count = count + 1
                        #print('p:', count)
                        self.state_points[j,i] = 1
                        self.state_points_index[count-1,0] = j
                        self.state_points_index[count-1,1] = i
                        #print(np.sum(self.state_points))

    def move_to_valid_points(self):

        #print('self iter', self.iteration)
        yi = int(self.state_points_index[self.iteration-1, 0])
        xi = int(self.state_points_index[self.iteration-1, 1])

        #print(yi,xi)
        z = self.city_array[yi, xi]
        self.observer_locations[0,0] = yi
        self.observer_locations[0,1] = xi
        self.observer_locations[0,2] = z

        #print('xyz', self.observer_locations)

    def moveto_closest_point(self):

        # given the point with the coor x,y,z find next positions
        is_done = 0
        n = -1
        move_step = self.move_step
        min_height = self.min_height

        while is_done==0:
            in_range = 0
            while in_range == 0:
                # current points
                x = random.randrange(self.im_width)
                y = random.randrange(self.im_height)

                if self.non_zero_mask[y,x] > 0:
                    in_range = 1

            # FOR EACH CAMERA:
            n = n + 1
            #print(n)
            radius = self.radius
            is_found = 0

            #print('y and x ',y,x)
            #y = self.observer_locations[n,0]
            #x = self.observer_locations[n,1]
            while is_found == 0:
                yx_coor = self.get_spiral(y,x,radius,move_step)
                h,w = yx_coor.shape
                observer_points = []
                #print('look')
                for i in range(h):
                    # FOR EACH POINT  AROUND THE CAMERA:
                    yi = yx_coor[i][0]
                    xi = yx_coor[i][1]

                    observer_height = self.city_array[yi, xi]
                    if observer_height > min_height:
                        # if the height of the camera is feasible,
                        # then find the sum of zero-value neighbours of the point
                        yx_i = self.get_spiral(yi,xi,1,1)
                        hi,wi = yx_i.shape
                        sum_nb = 0 # find the sum of zero neighbours
                        for j in range(hi):
                            # FOR EACH NEIGHBOUR OF THE POINT:
                            y_nb = yx_i[j][0]
                            x_nb = yx_i[j][1]
                            if self.city_array[y_nb, x_nb] < 3:
                                sum_nb = sum_nb + 1
                                #print('sum nb ', sum_nb)

                        if sum_nb > 3:
                            observer_distance = math.sqrt((y-yi)**2 + (x-xi)**2)
                            observer_points.append([yi, xi, observer_height, observer_distance])

                if len(observer_points) > 0:
                    is_found = 1
                    # version 1 : sort by h and get first row
                    #observer_points = sorted(observer_points, key=lambda l:l[3], reverse=False)
                    #r = 0
                    # version 2 : random
                    r = random.randrange(len(observer_points))
                    #print('r:', r)
                    next_y = observer_points[r][0]
                    next_x = observer_points[r][1]
                    next_z = observer_points[r][2]

                radius = radius + self.radius_delta

            # next_x next_y next_z
            #print('after y and x ',y,x)

            self.observer_locations_init[n,0] = y
            self.observer_locations_init[n,1] = x
            self.observer_locations_init[n,2] = next_z
            #print(self.observer_locations_init[n,0],self.observer_locations_init[n,1])

            #print('after nexty and nextx ',next_y,next_x)
            self.observer_locations[n,0] = next_y
            self.observer_locations[n,1] = next_x
            self.observer_locations[n,2] = next_z

            #print(self.observer_locations[n,0],self.observer_locations[n,1])
            if n == self.camera_number-1:
                is_done = 1

    def get_spiral(self, y, x, radius, move_step):

        '''
        Return the list of [y,x,z] points around the camera
        '''
        yx_list = []
        temp_yi = y-radius
        temp_xi = x-radius
        temp_yf = temp_yi + (2*radius+1)
        temp_xf = temp_xi + (2*radius+1)

        # move right (up)
        x_coor = np.arange(temp_xi, temp_xf+1, move_step)  # +1 to compensate the np.arange below
        y_coor = temp_yi*np.ones(len(x_coor))
        for i in range(len(x_coor)):
            yx_list.append([y_coor[i],x_coor[i]])

        # move down (right)
        y_coor = np.arange(temp_yi, temp_yf+1, move_step)
        x_coor = temp_xf*np.ones(len(y_coor))
        for i in range(len(y_coor)):
            yx_list.append([y_coor[i],x_coor[i]])

        # move right (bottom)
        x_coor = np.arange(temp_xi, temp_xf+1, move_step)
        y_coor = temp_yf*np.ones(len(x_coor))
        for i in range(len(x_coor)):
            yx_list.append([y_coor[i],x_coor[i]])

        # move down (left)
        y_coor = np.arange(temp_yi, temp_yf+1, move_step)
        x_coor = temp_xi*np.ones(len(y_coor))
        for i in range(len(y_coor)):
            yx_list.append([y_coor[i],x_coor[i]])

        # limit the xy_arr pairs [x,y]
        yx_arr = np.asarray(yx_list, dtype=np.int16)
        #print('before ', yx_arr)
        yx_arr1 = np.clip(yx_arr[:,0], 0, self.im_height-1)
        yx_arr2 = np.clip(yx_arr[:,1], 0, self.im_width-1)
        yx_arr = np.stack((yx_arr1,yx_arr2), axis = 1)
        #print('after ', yx_arr)
        return yx_arr

    def update_shapefile_random(self, shape_file, observer_loc):
        '''
        For all observer points
        Update the shapefile
        '''
        #update observer height and x and y
        fields = ['OFFSETA']
        tokens=['SHAPE@X', 'SHAPE@Y']
        with arcpy.da.UpdateCursor(shape_file,tokens+fields) as cursor:
            s = -1
            for row in cursor:
                s = s + 1
                row[0] = observer_loc[s,1] #observer_locations[s,0]
                row[1] = self.im_height - observer_loc[s,0] - 1 #observer_locations[s,1]
                row[2] = observer_loc[s,2]
                cursor.updateRow(row)
        del cursor

    def create_viewshed(self, input_raster, shape_file):

        analysis_type_ = self.analysis_type
        analysis_method_ = self.analysis_method
        radius_is_3d_ = self.radius_is_3d
        observer_height_ = self.observer_height
        vertical_lower_angle_ = self.vertical_lower_angle
        vertical_upper_angle_ = self.vertical_upper_angle
        inner_radius_ = self.inner_radius
        outer_radius_ = self.outer_radius
        start_t = time.time()


        outViewshed2 = Viewshed2(in_raster=input_raster, in_observer_features= shape_file, out_agl_raster= "", analysis_type= analysis_type_,
                                 vertical_error= 0, out_observer_region_relationship_table= "", refractivity_coefficient= 0.13,
                                 surface_offset= 0, observer_offset = 0, observer_elevation = "OFFSETA", inner_radius= inner_radius_,
                                 outer_radius= outer_radius_, inner_radius_is_3d = radius_is_3d_, outer_radius_is_3d = radius_is_3d_,
                                 horizontal_start_angle = 0, horizontal_end_angle= 360, vertical_upper_angle = vertical_upper_angle_,
                                 vertical_lower_angle= vertical_lower_angle_, analysis_method=analysis_method_)

        print('elapsed for viewshed', time.time() - start_t)
        output_array = arcpy.RasterToNumPyArray(outViewshed2) # output array -> each cell how many observer can see that pixel

        #output_array = self.city_array
        output_array[output_array == 255] = 0
        output_array = np.multiply(output_array, self.non_zero_mask)
        #print('shapes ', output_array.shape,self.non_zero_mask.shape )
        #print('elapsed for numpy', time.time() - start_t)
        visible_points = output_array > 0
        visible_area = visible_points.sum()
        ratio = visible_area/output_array.size

        return output_array, ratio
