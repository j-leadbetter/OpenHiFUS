# -*- coding: utf-8 -*-
"""
Created on Wed Jul 24 12:54:57 2013

@author: Michael
"""
import numpy as np
from matplotlib import pyplot as plt

try:
    import pyopencl as cl
    print "OpenCL Available"
except:
    pass



class Mux(object):
    def __init__(self, Elements = 64, UseOpenCL = False):
        '''
        Multiplexer class, to pass between various functions and HiFUS
        '''
        # General Parameters
        self.nElements = Elements
        self.Elements = range(self.nElements)

        self.maxAngles = 35
        self.Angles = range(-self.maxAngles,self.maxAngles)
        self.nAngles = len(self.Angles)

        self.Focals = [8e-3] #[6e-3, 8e-3, 12e-3]]
        self.nFocals = len(self.Focals)


        # Aquisitions Parameters
        self.nSamples = 320*5 # Samples per record
        self.nRecords = self.nFocals * self.nAngles
        self.nChannels = 2 # Number of active channels that can aquire Data
        self.nSamplesPerBuffer = self.nSamples * self.nRecords * self.nChannels
        self.nBuffers = (1 + (self.nElements-1) / self.nChannels ) * 2
        # NOTE: 2 is the safty factor, to have 1 buffer to work with while other is beeing written to
        # Increase if having timeout issues
        self.Offset = 500.0e-9 # Delay offset from master trigger to triggers
        self.SamplingRate = 500e6 # 500 Mega Samples Per Second

        self._calcDelays()

        # Data buffers
        self.Data = np.empty((self.nBuffers, self.nSamplesPerBuffer), dtype = np.uint16)
        self.Imagenx = self.nAngles
        self.Imageny = 3  *self.Imagenx
        self.Image = np.empty((self.Imageny, self.Imagenx), dtype = np.uint16)

        if UseOpenCL:
            try:
                clv = cl.VERSION_TEXT
                if not clv =="2012.1":
                    raise Exception('Update your PyOpenCL version to 2012.1!' )
            except:
                raise Exception('Please install PyOpenCL or set UseOpenCL=False !' )
            del clv
            # create an OpenCL context
            platform = cl.get_platforms()
            my_gpu_devices = platform[0].get_devices(device_type=cl.device_type.GPU)
            self.clCtx = cl.Context(devices=my_gpu_devices)
            self.clQueue = cl.CommandQueue(self.clCtx)

    def _calcDelays(self):
        c = 1.54e3 # Speed of cound in water
        ep = 3.8e-5 # Element Pitch

        self.Delay = np.zeros((self.nRecords * self.nElements), dtype=long)
        # Vector is used as it is easier to upload to Flash
        self.DelIdx = np.zeros((self.nRecords, self.nElements), dtype=int) # Matrix
        dt = 1.0 / self.SamplingRate

        iele = -1 # index of Elements
        for ele in self.Elements:
            iele += 1
            ifoc = -1 # index of Focals
            for foc in self.Focals:
                ifoc += 1
                iang = -1 # index of Angles
                for ang in self.Angles:
                    iang += 1
                    tmp = self.Offset + (foc-np.sqrt((foc*np.sin(np.radians(90+ang)))**2+(foc*np.cos(np.radians(90+ang))-(32-ele)*ep)**2))/(c)
                    # print int(Delay/dt)
                    self.Delay[iele*self.nFocals + ifoc*self.nAngles + iang] = tmp
                    self.DelIdx[ifoc*self.nAngles + iang,iele] = tmp / dt





    def BufPtrPlot(self):
        plt.figure(1)
        plt.axis([1000,0,64,-1])
        plt.title('Delay profile')
        plt.xlabel(r'Delay time [$ns$]')
        plt.ylabel('Element number')
        for i in range(len(self.Delay)/64):
#            print len(Dela[ i::RecordCnt ])
#            print Dela[ i::RecordCnt ]
            plt.plot(self.Delay[ i::self.nRecords ],self.Elements,'.-')
        plt.show()






# Test codes to make sure it's working

try:
    test = Mux()
    print 'Mux Initialisation sucess'
except:
    raise Exception('Mux Initialisation FAILED')


try:
    testcl = Mux(UseOpenCL=True)
    print 'MuxCL Initialisation sucess'
except:
    raise Exception('MuxCL Initialisation FAILED')

del test, testcl