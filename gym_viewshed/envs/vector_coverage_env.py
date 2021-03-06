"""
Created on Mon Nov 23 2020
@author: Daulet Baimukashev
"""

import numpy as np
from PIL import Image
import cv2
import time
import copy

import gym
from gym import error, spaces, utils
from gym.utils import seeding
import matplotlib.pyplot as plt

#import os
#os.environ['CUDA_VISIBLE_DEVICES'] = "0"

import math
from scipy import signal

class VectorCoverageEnv(gym.Env):
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
        0   Pan +5 deg
        1   Pan -5 deg
        2   Tilt +5 deg
        3   Tilt -5 deg
        4   Zoom +5 factor
        5   Zoom -5 factor

    Reward:
        Reward 1 for game over

    Starting State:
        Init image of the city

    Episode termination:
        Episode > 100

    """
    metadata = {'render.modes': ['human']}

    def __init__(self):

        # import image of city and convert values to height
        # Original image
        #self.city_array = np.array((Image.open(r"../data/images/RasterAstanaCropped.png")), dtype=np.uint16)
        # crop the image with center at camera location
        # self.camera_location = (3073, 11684, 350)   # x,y,z coordinate  #  (11685, 7074, 350) - RasterAstana.png
        # self.coverage_radius = 2000                 # .. km square from the center
        # self.city_array = self.city_array[self.camera_location[1]-self.coverage_radius:self.camera_location[1]+self.coverage_radius,
        #                                 self.camera_location[0]-self.coverage_radius:self.camera_location[0]+self.coverage_radius]

        # Resize 1000 > 250
        self.city_array = np.array((Image.open(r"../data/images/RasterAstanaCropped250x250.png")), dtype=np.uint16)
        self.city_array = self.city_array/100 - 285             # convert to meter

        # crop the image with center at camera location
        self.camera_location = (126, 126, 350)   # x,y,z coordinate  #  (11685, 7074, 350) - RasterAstana.png
        self.coverage_radius = 125                 # .. km square from the center or in pixels

        # Get image params
        self.im_height, self.im_width  = self.city_array.shape # reshape (width, height) [300,500] --> example: height = 500, width = 300

        # CAMERA params
        self.camera_number = 1
        self.camera_location_cropped = (int(self.coverage_radius), int(self.coverage_radius), (self.camera_location[2]-313)/4) # 313 or 285s

        self.observer_height = self.camera_location_cropped[2] + 2
        self.max_distance_min_zoom = 100/4       # at min zoom - 20mm - the max distance 50
        self.max_distance_max_zoom = 4000/4     # at min zoom - 800mm - the max distance 2000

        self.scale = 2
        self.horizon_fov_min = 0.5*self.scale       # 0.5      # at min zoom - 20mm - the max distance 50
        self.horizon_fov_max = 21*self.scale     # 21       # at min zoom - 20mm - the max distance 50

        self.vertical_fov_min =  0.3*self.scale    # 0.3        # 11.8        # Field of View deg
        self.vertical_fov_max =  11.8*self.scale   # 11.8         # 11.8        # Field of View deg

        # PTZ initalize
        self.pan_pos = 0 #360*np.random.rand()    # 0     np.random.rand()
        self.tilt_pos = -45 #-25*np.random.rand() # -45 
        self.zoom_pos = 20 # 20           # 0 - 20mm (min), 1 - 800 mm (max)

        print('ptz init: ', self.pan_pos, self.tilt_pos, self.zoom_pos)

        self.delta_pan  = 5                # deg
        self.delta_tilt = 2                 # deg
        self.delta_zoom = 1.25              # 1.25x times

        self.horizon_fov = self.horizon_fov_max               # 21           # Field of View deg
        self.vertical_fov =  self.vertical_fov_max            # 11.8        # Field of View deg
        self.zoom_distance = self.max_distance_min_zoom

        # GYM env params
        self.observation_space = spaces.Box(low=0, high=255, shape=(self.im_width,self.im_height, 1), dtype = np.uint8)
        self.action_space = spaces.Discrete(6)  # 6 different actions
        self.action = 0

        # render
        self.max_render = 100
        self.is_render = 'True'
        self.iteration = 0
        self.info = 0

        # reward
        self.ratio_threshhold = 0.02
        self.reward_good_step = 1
        self.reward_bad_step = -0.05
        self.max_iter = 300
        self.reward_temp = 0
        self.reward_prev = 0.0

        # coverage
        # self.city_coverage = np.asarray(Image.open(r"../data/images/RasterTotalCoverage.png"))
        self.city_coverage = np.asarray(Image.open(r"../data/images/RasterAstanaCropped250x250CoverageBinary.png"))
        self.rad_matrix, self.angle_matrix = self.create_cartesian()

        # inputs
        self.state_visible_points = np.zeros((self.im_height, self.im_width))
        self.state_total_coverage = self.city_coverage #np.zeros((self.im_height, self.im_width))
        self.state_gray_coverage = np.zeros((self.im_height, self.im_width))

    def step(self, action):

        #assert self.action_space.contains(action)
        # move the ptz
        self.move_ptz(action)

        # create the viewshed
        output_array, num_visible_points = self.get_coverage_fast()

        # interpret the viewshed output to some value - state , reward etc

        # for rendering
        self.state_visible_points = output_array

        ##########################
        # reward ???
        ##########################

        crossed_map = np.multiply(self.state_total_coverage,self.state_visible_points)
        crossed_points = (crossed_map > 0).astype(int).sum()

        # option 1
        reward = (crossed_points - 20) / 100
        
        # option 2
        reward_curr = crossed_points / 100
        # ------------------------------------------------
        #if num_visible_points < 50:
        #    coef_visible_points = 0.03
        #elif num_visible_points > 200:
        #    coef_visible_points = 0.03
        #else:
        #    coef_visible_points = 1.0
        
        gausian_point = min(num_visible_points, 500)
        #print(gausian_point)
        gausian_scale = signal.gaussian(501, std=50)
        coef_visible_points = gausian_scale[gausian_point]

        step_cost = 0.2
        reward = (1-coef_visible_points)/5 + coef_visible_points * reward_coverage - step_cost
        # print(num_visible_points, coef_visible_points)

        self.reward_prev = reward_curr

        # Total Covered
        # 1 - self.state_total_coverage - already covered points
        self.state_total_coverage = np.multiply(self.state_total_coverage,(1-self.state_visible_points))
        total_cover_ratio = ((self.state_total_coverage>0).astype(int).sum())/(251*251)

        # done ???
        #if (self.iteration > self.max_iter) or total_cover_ratio < 0.05:
        #    done = 1
        #    self.info = 1.0
        #else:
        #    done = 0

        #reward = -0.01
        if (self.iteration > self.max_iter):
            done = 1
            reward = -5
            self.info = 1.0
        else:
            done = 0

        if total_cover_ratio < 0.05:
            done = 1
            reward = 5
            self.info = 1.0
        
        
        # next_state ???

        # 2 - separate
        # self.state_gray_coverage = np.add(self.state_gray_coverage, self.state_visible_points)
        # self.state_gray_coverage[self.state_gray_coverage>0] = 127
        #
        # self.state_total_coverage = np.add(self.city_coverage, -self.state_gray_coverage)
        # self.state_total_coverage[self.state_total_coverage<0] = 0
        #
        # print(np.max(np.max(self.city_coverage )) , np.max(np.max(self.state_total_coverage )))

        # print('---> ', type(self.state_total_coverage), type(self.state_visible_points))
        # print('---------> ', np.sum(np.sum(self.state_total_coverage/255))/self.state_total_coverage.size,
        #                         np.sum(np.sum(self.state_visible_points))/self.state_total_coverage.size)

        next_state = np.stack((self.state_total_coverage/255.0, self.state_visible_points), axis = 0)
        self.iteration = self.iteration + 1

        return next_state, reward, done, self.info

    def seed(self, seed = None):
        self.np_random , seed = seeding.np_random(seed)
        return [seed]

    def reset(self):
        self.iteration = 0

        # position
        self.pan_pos = 360*self.np_random.rand()    #360*np.random.rand()    # 0     np.random.rand()
        self.tilt_pos = -45*self.np_random.rand()        # -45*np.random.rand() # -45 
        self.zoom_pos = 120     # 0 - 20mm (min), 1 - 800 mm (max)

        self.horizon_fov = self.horizon_fov_max/(self.delta_zoom**8)
        self.vertical_fov =  self.vertical_fov_max/(self.delta_zoom**8)
        self.zoom_distance = self.max_distance_min_zoom*(self.delta_zoom**8)

        # state
        self.state_visible_points = np.zeros((self.im_height, self.im_width))
        self.state_total_coverage = self.city_coverage
        next_state = np.stack((self.state_total_coverage/255.0, self.state_visible_points), axis = 0)

        return next_state

    def render(self, mode='human'):

        # show city in RGB (green + blue) and temp covered points in red
        city_gray = np.array(self.city_array, dtype=np.uint8)
        show_array = np.stack((city_gray,)*3, axis=-1)

        show_array[:,:,2] = self.state_visible_points*255
        #show_array[:,:,2] = np.multiply(self.state_visible_points, 255-np.array(self.city_coverage, dtype='uint8'))
        #show_array = cv2.resize(show_array, (1000,1000), interpolation = cv2.INTER_AREA)

        # show the  covered points
        show_array2 = np.array(self.state_total_coverage, dtype='uint8')
        #show_array2 = cv2.resize(show_array2, (1000,1000), interpolation = cv2.INTER_AREA)

        font                   = cv2.FONT_HERSHEY_SIMPLEX
        bottomLeftCornerOfText = (10,700)
        bottomLeftCornerOfText2 = (10,750)
        bottomLeftCornerOfText3 = (10,800)
        fontScale              = 0.5
        fontColor              = (0,0,255)
        lineType               = 1

        try:
            cv2.startWindowThread()

            action_dict = {
                "0": "pan right (+10 deg)",
                "1": "pan left (-10 deg)",
                "2": "tilt up (+3 deg)",
                "3": "tilt down (-3 deg)",
                "4": "zoom in (1.25x)",
                "5": "zoom out (0.8x)"
                }

            action_display = 'Last Action: {},         Reward: {}'.format(action_dict[str(self.action)], self.reward_temp)

            text_display = 'Pan: {}, Tilt: {}, Zoom: {:.2f}'.format(
                            self.pan_pos, self.tilt_pos, self.zoom_pos/20)

            text_display2 = 'Max distance: {:.2f}, Horizontal FOV: {:.2f}, Vertical FOV: {:.2f}'.format(
                            self.zoom_distance, self.horizon_fov, self.vertical_fov)

            cv2.putText(show_array,'Current field of view of the camera', (10,220), font, fontScale, (255,255,255), lineType)
            cv2.putText(show_array2,'Covered Points by the camera (union)', (10,220), font, fontScale, (255,255,255), lineType)
            cv2.putText(show_array,action_display, bottomLeftCornerOfText, font, fontScale, fontColor, lineType)
            cv2.putText(show_array,text_display, bottomLeftCornerOfText2, font, fontScale, fontColor, lineType)
            cv2.putText(show_array,text_display2, bottomLeftCornerOfText3, font, fontScale, fontColor, lineType)

            cv2.namedWindow("city")
            cv2.imshow("city", show_array)

            cv2.namedWindow("coverage")
            cv2.imshow("coverage", show_array2)

            cv2.waitKey(5)
        except KeyboardInterrupt:
            cv2.destroyAllWindows()


    def close(self):
        pass

    def move_ptz(self, action_type):

        # Type: Discrete
        # Num Action
        # 0   Pan +5 deg
        # 1   Pan -5 deg
        # 2   Tilt +5 deg
        # 3   Tilt -5 deg
        # 4   Zoom +5 factor
        # 5   Zoom -5 factor
        self.action = action_type

        if action_type == 0:    # rotate + delta
            #print('... pan right')
            # update camera/ptz setting
            self.pan_pos += self.delta_pan
            if self.pan_pos >= 360:
                self.pan_pos -= 360

        elif action_type == 1:    # rotate - delta deg
            #print('... pan left')
            # update camera/ptz setting
            self.pan_pos -= self.delta_pan
            if self.pan_pos < 0:
                self.pan_pos += 360

        elif action_type == 2:    # tilt + deg
            #print('... tilt up')
            # update camera/ptz setting
            self.tilt_pos += self.delta_tilt
            if self.tilt_pos > 0:
                self.tilt_pos = 0

        elif action_type == 3:    # tilt - deg
            #print('... tilt down')
            # update camera/ptz setting
            self.tilt_pos -= self.delta_tilt
            if self.tilt_pos < -45:
                self.tilt_pos = -45


        elif action_type == 4:    # zoom + in
            #print('... zoom in')
            # update camera/ptz setting
            self.zoom_pos *= self.delta_zoom

            self.horizon_fov /= self.delta_zoom
            self.vertical_fov /= self.delta_zoom
            self.zoom_distance *= self.delta_zoom

            # boundaries
            if self.zoom_pos > 800:
                self.zoom_pos = 800

            if self.horizon_fov < self.horizon_fov_min:
                self.horizon_fov = self.horizon_fov_min

            if self.vertical_fov < self.vertical_fov_min:
                self.vertical_fov = self.vertical_fov_min

            if self.zoom_distance > self.max_distance_max_zoom:
                self.zoom_distance = self.max_distance_max_zoom

        elif action_type == 5:    # zoom - out
            #print('... zoom out')

            # update camera/ptz setting
            self.zoom_pos /= self.delta_zoom

            self.horizon_fov *= self.delta_zoom
            self.vertical_fov *= self.delta_zoom
            self.zoom_distance /= self.delta_zoom

            # boundaries
            if self.zoom_pos < 20:
                self.zoom_pos = 20

            if self.horizon_fov > self.horizon_fov_max:
                self.horizon_fov = self.horizon_fov_max

            if self.vertical_fov > self.vertical_fov_max:
                self.vertical_fov = self.vertical_fov_max

            if self.zoom_distance < self.max_distance_min_zoom:
                self.zoom_distance = self.max_distance_min_zoom
        else:
            pass
            print('No action done ..')


    def create_cartesian(self):

        rad_matrix = np.zeros((self.im_height, self.im_width))
        angle_matrix = np.zeros((self.im_height, self.im_width))

        for i in range(self.im_height):
            for j in range(self.im_width):

                point_rad  = math.sqrt((self.coverage_radius-i)**2 + (self.coverage_radius-j)**2)

                point_angle = math.degrees(math.atan2((self.coverage_radius-i),(j-self.coverage_radius)))
                point_angle *= -1
                point_angle += 90
                if point_angle < 0:
                    point_angle += 360


                rad_matrix[i,j] = point_rad
                angle_matrix[i,j] = point_angle

        return rad_matrix, angle_matrix

    def get_coverage_fast(self):
        start_t = time.time()
        output_array = np.zeros((self.im_height, self.im_width))

        temp_angle = self.pan_pos

        horizon_start = temp_angle - self.horizon_fov/2
        horizon_end = temp_angle + self.horizon_fov/2
        if horizon_start < 0:
            horizon_start += 360
        if horizon_end >= 360:
            horizon_end -= 360

        vertical_start =  self.tilt_pos - self.vertical_fov/2
        vertical_end = self.tilt_pos + self.vertical_fov/2

        if vertical_start < 0 and vertical_end < 0:

            radius_inner = self.observer_height*math.tan(math.radians(90+vertical_start))
            radius_outer = self.observer_height*math.tan(math.radians(90+vertical_end))
            if radius_outer > self.zoom_distance:
                radius_outer = self.zoom_distance

            # matrix
            rad_matrix, angle_matrix = self.rad_matrix, self.angle_matrix

            inside_rad = np.multiply( np.greater_equal(rad_matrix, radius_inner), np.greater_equal(radius_outer, rad_matrix))

            if horizon_start < horizon_end:
                inside_angle = np.multiply(np.greater_equal(angle_matrix, horizon_start), np.greater_equal(horizon_end, angle_matrix))
            else:
                inside_angle = np.add(np.greater_equal(angle_matrix, horizon_start), np.greater_equal(horizon_end, angle_matrix))

            inside_sector = np.multiply(inside_rad, inside_angle)

            # print('Here --- ', inside_rad.shape, inside_angle.shape, inside_sector.shape)
            # print('2 - coverage : horizon_start {},  horizon_end {} , vertical_start {}, vertical_end {}, radius_inner{}, outer_radius {}'.format(
            #        horizon_start, horizon_end, vertical_start, vertical_end, radius_inner, radius_outer))

            output_array = inside_sector
            #print('Elapsed time for coverage: ', time.time() - start_t)

            output_array = output_array.astype(int)
            output_array[output_array>1] = 1

            visible_points = (output_array > 0).astype(int)
            visible_area = visible_points.sum()

        else:
            #print('Tilt Angle is larger than zero !!!')
            visible_area = 0

        return output_array, visible_area
