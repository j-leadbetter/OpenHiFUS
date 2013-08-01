# -*- coding: utf-8 -*-
"""
Created on Wed Jul 24 12:54:57 2013

@author: Michael
"""
import numpy as np
from matplotlib import pyplot as plt
import pylab as pyl
import time

try:
    import pyopencl as cl
    print "OpenCL Available"
except:
    pass


clkernel = """
__kernel void RenderImg(__global unsigned int* Data, __global unsigned int* Image, __global unsigned int* ScaleFac, __global unsigned int* nElems,  __global unsigned int* nSam, __global unsigned int* DelIdx, __global unsigned int* AF)
{
    //get our index in the array
    unsigned int yy = get_global_id(0);
    unsigned int xx = get_global_id(1);
    printf((__constant char *)"x%d ", xx);
    printf((__constant char *)"y%d ", yy);
    //printf((__constant char *)"%d           ", Data[xx,yy]);
    long nn;
    for (nn = 0; nn<64; nn++)
    {
        printf( (__constant char *) "%d    ", nn);
        // Each pixel takes data from each channel
        //BufPos = self.ActiveFrame * self.nElements + nn # Buffer number to be used
    }

//
//        PixVal = 0
//        RecPos = xx * self.nSamples + yy * scaleFactor + self.DelIdx[xx, nn] #Delay Index for angle xx, for element nn
//#       print 'element', nn
//#       print self.Data[BufPos, RecPos:RecPos+scaleFactor]
//        for kk in range(scaleFactor): # Each element was oversampled per pixel
//            if (RecPos + kk) > ( (xx+1) * self.nSamples): # You're on next record;
//                 PixVal += 0
//            else:
//                 PixVal += self.Data[BufPos, RecPos + kk]
//#       print 'sum', PixVal / scaleFactor
//        Img[yy, xx] += PixVal / scaleFactor  # Add contribution of the Element

}
"""




class Mux(object):
    def __init__(self, Elements = 64, maxAngles = 35, Focals = [8.0e-3], UseOpenCL = False):
        '''
        Multiplexer class, to pass between various functions and HiFUS
        '''
        # General Parameters
        self.nElements = Elements
        self.Elements = range(self.nElements)

        self.maxAngles = maxAngles
        self.Angles = range(-self.maxAngles,self.maxAngles)
        self.nAngles = len(self.Angles)

        self.Focals = Focals #[6e-3, 8e-3, 12e-3]]
        self.nFocals = len(self.Focals)


        # Aquisitions Parameters
        self.nSamples = 320*5 # Samples per record
        self.nRecords = self.nFocals * self.nAngles
        self.nChannels = 2 # Number of active channels that can aquire Data
        self.nSamplesPerBuffer = self.nSamples * self.nRecords * self.nChannels
        self.Frames = 2
        self.ActiveFrame = 0
        self.nBuffers = (1 + (self.nElements-1) / self.nChannels ) * self.Frames
        # NOTE: 2 is the safty factor, to have 1 buffer to work with while other is beeing written to
        # Increase if having timeout issues
        self.Offset = 500.0e-9 # Delay offset from master trigger to triggers
        self.SamplingRate = 500e6 # 500 Mega Samples Per Second

        self._calcDelays()

        # Data buffers
        self.Data = np.zeros((self.nBuffers, self.nSamplesPerBuffer), dtype = np.uint16)
        self.Imagenx = self.nAngles
        i = 1
        while (self.nSamples/i >= 2*self.Imagenx) or not int(self.nSamples/float(i))==(self.nSamples/float(i)):
            i += 1
        self.Imageny = self.nSamples / i
        self.Image = np.zeros((self.Imageny, self.Imagenx), dtype = np.uint32)

        self.UseCL = False

        if UseOpenCL:
            self.__initCL__()

    def __initCL__(self):
        try:
            clv = cl.VERSION_TEXT
            if not clv =="2013.1":
                raise Exception('Update your PyOpenCL version to 2013.1!' )
        except:
            raise Exception('Please install PyOpenCL or set UseOpenCL=False !' )
        del clv
        # create an OpenCL context
        platform = cl.get_platforms()
        my_gpu_devices = platform[0].get_devices(device_type=cl.device_type.GPU)
        self.clCtx = cl.Context(devices = my_gpu_devices)
        self.clQueue = cl.CommandQueue(self.clCtx)
        self.UseCL = True


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
                    self.DelIdx[ifoc*self.nAngles + iang,iele] = tmp / dt #TODO Is this times 2? As there is two times the delay?


    def _RenderImgGPU(self, scaleFactor):
        c = 1.54e3 # Speed of cound in water
        ep = 3.8e-5 # Element Pitch
        if not self.UseCL:
            raise Exception('Please install PyOpenCL or set UseOpenCL=False !')
        # for a (input), we need to specify that this buffer should be populated from a
        Data_buf = cl.Buffer(self.clCtx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=self.Data)
        # for b (output), we just allocate an empty buffer
        Image_buf = cl.Buffer(self.clCtx, cl.mem_flags.WRITE_ONLY, self.Image.nbytes)
        SF_buf = cl.Buffer(self.clCtx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=np.array(scaleFactor))
        nElements_buf = cl.Buffer(self.clCtx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=np.array(self.nElements))
        nSamples_buf = cl.Buffer(self.clCtx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=np.array(self.nSamples))
        DelIdx_buf = cl.Buffer(self.clCtx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=np.array(self.DelIdx))
        AF_buf = cl.Buffer(self.clCtx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=np.array(self.ActiveFrame))
        Program = cl.Program(self.clCtx, clkernel).build()
#        Event = Program.RenderImg(self.clQueue, (self.Imageny, self.Imagenx), Data_buf, Image_buf, SF_buf, nElements_buf, nSamples_buf, DelIdx_buf, AF_buf)
        Event = Program.RenderImg(self.clQueue, (1, 1), None, Data_buf, Image_buf, SF_buf, nElements_buf, nSamples_buf, DelIdx_buf, AF_buf)
        Event.wait()
        Img = np.zeros([m.Imageny,m.Imagenx], dtype = np.uint32)
        cl.enqueue_copy(self.clQueue, Img, Image_buf)
        return Img

    def _RenderImgCPU(self, scaleFactor):
        t1 = time.time()
        Img = np.zeros([m.Imageny,m.Imagenx], dtype = np.uint32)
        for yy in range(self.Imageny): # Iterate over all pixels
            print 'Working on line', yy
            for xx in range(self.Imagenx):
#                print 'Working on pixel', yy, xx
                PixVal = 0
                for nn in range(self.nElements): # Each pixel takes data from each channel
                    BufPos = self.ActiveFrame * self.nElements + nn # Buffer number to be used
                    RecPos = xx * self.nSamples + yy * scaleFactor + self.DelIdx[xx, nn] #Delay Index for angle xx, for element nn
#                    print 'element', nn
#                    print self.Data[BufPos, RecPos:RecPos+scaleFactor]
                    for kk in range(scaleFactor): # Each element was oversampled per pixel
                        if (RecPos + kk) > ( (xx+1) * self.nSamples): # You're on next record;
                            PixVal += 0
                        else:
                            PixVal += self.Data[BufPos, RecPos + kk]
#                    print 'sum', PixVal / scaleFactor
                Img[yy, xx] = PixVal / scaleFactor  # Add contribution of the Element
#                print 'pixel', yy, xx, Img[yy, xx]
        print time.time() - t1
        return Img



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

    def RenderImage(self):
        scaleFactor = self.nSamples / self.Imageny
        print scaleFactor
        if (self.UseCL):
            self.Image = self._RenderImgGPU(scaleFactor)
        else:
            self.Image = self._RenderImgCPU(scaleFactor)
        # Temp variable Img to manipulate


    def ShowImage(self):
        plt.figure(2)
        plt.imshow(self.Image)
        plt.show()

    def RandBuffer(self):
        self.Data = np.random.randint(0, 2**12, size = np.shape(self.Data))

    def NextFrame(self):
        if self.ActiveFrame == self.Frames:
            self.ActiveFrame = 0
        self.ActiveFrame += 1


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

m = Mux(UseOpenCL=True)
m.RandBuffer()

