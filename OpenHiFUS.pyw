"""
OpenHiFUS
Copyright 2012-2013 Jeff Leadbetter
jeff.leadbetter@dal.ca

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

#Title: OpenHiFUS
version='1.03'
#Date: August 6, 2013
#Python Version 2.7.2

import os
import platform
import sys
from PyQt4.QtCore import *
from PyQt4.QtGui import *

import numpy
import numpy.random
import serial
import struct
import time
import multiprocessing
import cv2

try:
    import pyopencl as cl
except:
    pass

from guiqwt.plot import ImageWidget
from guiqwt.plot import ImageDialog
from guiqwt.plot import CurveDialog
from guiqwt.builder import make
#make is an alias for guiqwt.builder.PlotItemBuilder()
#from guiqwt.tools import ContrastPanelTool
#see guiqwt.image.RawImageItem  for additional methods on image adjustment


FIXEDSIZE = True
MULTIPROCESS = True
USEOCL = False

#SEE END OF FILE FOR HARDWARE IMPORT


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        """
        Main window for OpenHiFUS ultrasound imaging applicaiton

        """
        super(MainWindow, self).__init__(parent)

        self.setWindowTitle("OpenHiFUS "+version)

        #Set central widget - Main Scan window
        self.mainWindow = MainScanWindow()
        self.setCentralWidget(self.mainWindow)

        #Set main toolbar
        mainToolBar = self.addToolBar("Tools")

        #Set MCU - micro control unit - as initial dock widget
        self.mcuWidget = MCUWidget()

        mcuDockWidget = QDockWidget('MCU Settings', self)
        mcuDockWidget.setObjectName('mcuDockWidget')
        mcuDockWidget.setAllowedAreas(Qt.LeftDockWidgetArea)
        mcuDockWidget.setWidget(self.mcuWidget)
        self.addDockWidget(Qt.LeftDockWidgetArea, mcuDockWidget)

        #Provide reference to the MCU in widgets that require them
        self.mainWindow.BModeTab.setMCU(self.mcuWidget)
        self.mainWindow.MModeTab.setMCU(self.mcuWidget)

    def closeEvent(self, event):
        """
        Clean up child widgets before exit

        1) Close the active COM port before application exit
        2) Kill the child process if MULTIPROCESS is True

        """
        self.mcuWidget.MCU.close()
        self.mainWindow.dataObject.terminate()

        event.accept()


class MainScanWindow(QWidget):
    def __init__(self, parent=None):
        super(MainScanWindow, self).__init__(parent)

        #All imaging modes access the same data object
        #This is owned by the MainScanWindow widget and
        #referenced by the individual image mode widgets
        self.dataObject = HiFUSData()


        #GUI appearance
        BModePalette = QPalette()
        BModePalette.setColor(QPalette.Window, Qt.black)
        BModePalette.setColor(QPalette.WindowText, Qt.white)

        MModePalette = QPalette()
        MModePalette.setColor(QPalette.Window, Qt.darkGray)
        MModePalette.setColor(QPalette.WindowText, Qt.white)


        #Each imaging mode widget is given a tab in the central widget
        self.imageModeTabs = QTabWidget()
        tab = 0

        #B Mode Imaging
        self.BModeTab = BModeWindow(self.dataObject)
        self.BModeTab.setAutoFillBackground(True)
        self.BModeTab.setPalette(BModePalette)
        self.BModeTab.setAppearance()
        self.imageModeTabs.insertTab(tab,self.BModeTab, 'B Mode')
        tab += 1

        #M Mode Imaging
        self.MModeTab = MModeWindow(self.dataObject)
        self.MModeTab.setAutoFillBackground(True)
        self.MModeTab.setPalette(MModePalette)
        self.imageModeTabs.insertTab(tab,self.MModeTab, 'M Mode')
        tab += 1

        #RF Scan Lines
        self.RFTab = RFWindow(self.dataObject)
        self.RFTab.setAutoFillBackground(True)
        self.RFTab.setPalette(MModePalette)
        self.imageModeTabs.insertTab(tab, self.RFTab, 'RF Data')
        tab += 1

        #End imaging mode list

        #Set the GUI layout
        grid = QGridLayout()
        grid.addWidget(self.imageModeTabs,0,0)
        self.setLayout(grid)


class BModeWindow(QWidget):
    def __init__(self, dataObject, parent=None):
        """
        Class contains GUI tools and layout for B mode imaging

        Required Arguments

        dataObject:  Inherits QObject. Is responsible for interfacing with
                     data acquisition hardware, data storage and memory assignment,
                     boradcasting data to main GUI, and providing physical parameters
                     related to plotting. During scanning or replay plots are updated
                     when the 'newBData' signal is recieved from the dataObject.
        """
        super(BModeWindow, self).__init__(parent)

        #-------------------
        #B mode data members
        #-------------------
        self.dataObject = dataObject

        #Scanner Micro Controller
        #Assigned after init() using setMCU() method
        self.MCU = None

        #------------------
        # GUI widgets setup
        #------------------

        #Set "Run" and "Stop" buttons
        self.runButton  = QPushButton("Scan")
        self.stopButton = QPushButton("Stop")
        self.saveButton = QPushButton("Export RF Data")

        #Label to report framerate
        self.frameRate = 0.0
        self.frameRateLabel = QLabel()
        self.fpsClock = time.clock


        #BMode image display uses guiqwt.plot.ImageDialog()
        self.plotDialog = ImageDialog(edit=False, toolbar=False,
                                      options=dict(show_contrast=False, \
                                                   aspect_ratio = 1.00, \
                                                   xlabel="Position (mm)", \
                                                   ylabel="Depth (mm)", \
                                                   ysection_pos="left"))



        #Create a local image data array and a guiqwt.image.ImageItem
        imgyPx, imgxPx = self.dataObject.BData.shape
        self.currentImageData = numpy.zeros([imgxPx, imgyPx])
        imgWidth = self.dataObject.getBWidth()
        imgDepth = self.dataObject.getBDepth()
        self.currentImage     = make.image(self.currentImageData, \
                                           xdata = imgWidth, \
                                           ydata = imgDepth, \
                                           colormap='gist_gray')

        #Set the dynamic range
        imgRange = dataObject.getBRange()
        self.currentImage.set_lut_range(imgRange)
        #Set the plot size and add the image
        dx = abs(imgWidth[1]-imgWidth[0])
        dy = abs(imgDepth[1]-imgDepth[0])
        plot = self.plotDialog.get_plot()
        if FIXEDSIZE is True:
            nativeSize = QSize(650*dx/dy,580)
            plot.setMaximumSize(nativeSize)
            plot.setMinimumSize(nativeSize)
        plot.add_item(self.currentImage)
        plot.set_active_item(self.currentImage)

        #Image adjust tools
        #TODO: Move these to a dock-able toolbox

        #Signal Range
        self.BSignalRange = dataObject.getBRange()
        self.BSignalRangeSlider = QSlider(Qt.Horizontal)
        self.BSignalRangeSlider.setMinimum(0)
        self.BSignalRangeSlider.setMaximum(self.BSignalRange[1])
        self.BSignalRangeSlider.setValue(self.BSignalRange[1])

        #Noise Floor
        self.BNoiseFloorSlider = QSlider(Qt.Horizontal)
        self.BNoiseFloorSlider.setMinimum(0)
        self.BNoiseFloorSlider.setMaximum(self.BSignalRange[1])
        self.BNoiseFloorSlider.setValue(0)

        #BMode data averaging
        maxAveragesExp = 3
        self.maxAverages = 2**maxAveragesExp
        self.averageList = [2**(x) for x in range(0,maxAveragesExp+1)]
        averageText = ["%d Frames" % i for i in self.averageList]
        self.averageComboBox = QComboBox()
        self.averageComboBox.addItems(averageText)

        #Flip Image Left to Right
        self.flipLRButton = QPushButton('Flip L/R')
        self.flipLRButton.setCheckable(True)

        #Time Gain
        self.gainWidget = TimeGainWidget(dataLength=dataObject.RFRecordLength)

        #Replay
        self.replayWidget = ReplayWidget(self.dataObject)


        #-----------
        # GUI layout
        #-----------

        grid = QGridLayout()
        row = 0

        runStopStack = QVBoxLayout()
        runStopStack.addWidget(self.runButton)
        runStopStack.addWidget(self.stopButton)
        runStopInterface = QHBoxLayout()
        runStopInterface.addLayout(runStopStack)
        runStopInterface.addStretch()
        grid.addLayout(runStopInterface, row, 0)
        row += 1

        frameRateLayout = QHBoxLayout()
        frameRateLayout.addWidget(QLabel('Frame Rate (fps): '))
        frameRateLayout.addWidget(self.frameRateLabel)
        frameRateLayout.addStretch()
        grid.addLayout(frameRateLayout, row, 0)
        row += 1

        line = QFrame(self)
        line.setLineWidth(1)
        line.setFrameStyle(QFrame.HLine)
        grid.addWidget(line)
        row += 1

        grid.addWidget(QLabel("Noise Floor Adjust (dB):"),row,0)
        row += 1
        grid.addWidget(self.BNoiseFloorSlider)
        self.BNoiseFloorSlider.setSizePolicy(QSizePolicy(QSizePolicy.Preferred))
        row += 1

        grid.addWidget(QLabel("Maximum Signal Adjust (dB):"),row,0)
        row += 1
        grid.addWidget(self.BSignalRangeSlider)
        self.BSignalRangeSlider.setSizePolicy(QSizePolicy(QSizePolicy.Preferred))
        row += 1

        grid.addWidget(QLabel('Averaging :'),row,0)
        row += 1
        grid.addWidget(self.averageComboBox, row,0)
        self.averageComboBox.setSizePolicy(QSizePolicy(QSizePolicy.Preferred))
        row += 1

        plotLayout = QGridLayout()
        plotLayout.addWidget(self.plotDialog,0,0)
        plotLayout.addWidget(self.gainWidget,0,1)
        plotLayout.addWidget(self.flipLRButton,1,1)
        plotLayout.addWidget(self.replayWidget,1,0)

        plotVSpacer = QVBoxLayout()
        plotVSpacer.addStretch()
        plotVSpacer.addLayout(plotLayout)
        plotVSpacer.addStretch()
        plotHSpacer = QHBoxLayout()
        plotHSpacer.addStretch()
        plotHSpacer.addLayout(plotVSpacer)
        plotHSpacer.addStretch()
        grid.addLayout(plotHSpacer, row, 0)
        row += 1

        self.saveButton.setSizePolicy(QSizePolicy(QSizePolicy.Preferred))
        grid.addWidget(self.saveButton)
        row += 1

        self.setLayout(grid)

        #------------------
        # Signals and slots
        #------------------
        self.connect(self.runButton,   SIGNAL("clicked()"), self.runBScan)
        self.connect(self.stopButton,  SIGNAL("clicked()"), self.stopBScan)
        self.connect(self.BSignalRangeSlider, SIGNAL("valueChanged(int)"), self.setBMaxPlotRange)
        self.connect(self.BNoiseFloorSlider, SIGNAL("valueChanged(int)"), self.setBMinPlotRange)
        self.connect(self.averageComboBox, SIGNAL("currentIndexChanged(int)"), self.setBAverage)
        self.connect(self.flipLRButton, SIGNAL("clicked()"), self.flipLeftRight)
        self.connect(self.gainWidget,  SIGNAL("newTimeGain"), self.setTimeGain)
        self.connect(self.saveButton,  SIGNAL("clicked()"), self.exportRFData)
        self.connect(self.dataObject,  SIGNAL("newBData"),  self.replot)
        self.connect(self.dataObject,  SIGNAL("faildata"),  self.stopBScan)

    def runBScan(self):
        """ Method calls program loop to acquire B mode images """
        if self.MCU is not None:
            self.MCU.setAC()

        #Calculate display frame rate
        self.preClock = self.fpsClock()

        #Start data collection
        self.dataObject.setBMode()
        #self.dataObject.setTimeGain(self.gainWidget.gain)
        self.dataObject.collect()

    def stopBScan(self):
        """ Stop B Mode Image Acquisition """
        try:
            self.dataObject.alive = False
        except:
            pass

        if self.MCU is not None:
            self.MCU.setDC()

    def setBMaxPlotRange(self, sliderIndex):
        sliderIndex = max(1, sliderIndex)
        self.BSignalRange[1] = sliderIndex
        a, b = self.BSignalRange
        self.currentImage.set_lut_range([a, b])
        self.plotDialog.plot_widget.contrast.set_range(a, b)
        plot = self.plotDialog.get_plot()
        plot.set_active_item(self.currentImage)
        plot.replot()

    def setBMinPlotRange(self, sliderIndex):
        sliderIndex = min(59, sliderIndex)
        self.BSignalRange[0] = sliderIndex
        a, b = self.BSignalRange
        self.currentImage.set_lut_range([a, b])
        self.plotDialog.plot_widget.contrast.set_range(a, b)
        plot = self.plotDialog.get_plot()
        plot.set_active_item(self.currentImage)
        plot.replot()

    def setBAverage(self, index):
        #Parse out the number of frames to average from the combo box text
        temp = int(str(self.averageComboBox.currentText()).split()[0])
        self.dataObject.setBAverage(temp)

    def setTimeGain(self, gain):
        self.dataObject.setTimeGain(gain)

    def flipLeftRight(self):
        """Flip the image from left to right """
        flip = self.flipLRButton.isChecked()
        plot = self.plotDialog.get_plot()
        plot.set_axis_direction('bottom', flip)
        plot.set_active_item(self.currentImage)
        plot.replot()

    def replot(self, imageData):
        """ Update all B Mode images and related data display """
        self.currentImageData = imageData
        self.currentImage.set_data(self.currentImageData)
        self.currentImage.set_lut_range(self.BSignalRange)
        plot = self.plotDialog.get_plot()
        plot.replot()
        #plot.set_active_item(self.currentImage)

        self.curClock = self.fpsClock()
        self.frameRate = 2.0 / ( self.curClock-self.preClock)
        self.frameRateLabel.setText('{:.1f}'.format(self.frameRate))
        self.preClock = self.curClock

        #TO DO: see documentaiton on guiqwt.plot.PlotManager,
        #for info on updating contrast panel and cross-section plots


    def setMCU(self, MCU):
        """ Assign a local reference to the scanner MCU """
        self.MCU = MCU

    def exportRFData(self):

        if MULTIPROCESS == True and self.dataObject.alive == True:
             QMessageBox.warning(self, "User Action Required", "Scanning must be stopped before buffer export.")

        else:
            #Now save the current data
            filename = QFileDialog.getSaveFileName(self, 'Save File')
            if filename != "":
                outBuffer = self.dataObject.getCurrentBuffer()
                numpy.save(str(filename), outBuffer)

    def setAppearance(self):
        """
        The GuiQWT objects don't repaint when their parents palette
        is updated. Apply palette here with any modifications wanted.
        """

        windowPalette = self.palette()

        #Set the axis values to general foreground color
        #These are defined by QPallet.Text, which makes them init
        #diferently from the general foreground (WindowText) color.
        plotPalette = self.plotDialog.palette()
        plotPalette.setColor(QPalette.Text, windowPalette.color(QPalette.WindowText))
        plotPalette.setColor(QPalette.WindowText, windowPalette.color(QPalette.WindowText))
        self.plotDialog.setPalette(plotPalette)
        self.plotDialog.palette()
        #Need to set the axis labels manually...
        plot = self.plotDialog.get_plot()
        plot.set_axis_color('bottom', windowPalette.color(QPalette.WindowText))
        plot.set_axis_color('left', windowPalette.color(QPalette.WindowText))



class TimeGainWidget(QWidget):
    def __init__(self, sliderCount=5, dataLength=6080, maxGain=20, parent=None):
        """
        Widget to produce a display of sliders for setting the
        post-processing time gain cure in BMode images.

        Input  - sliderCount, number of sliders to use. Each slider gives a log
                              scale gain value
               - dataLength, number of data points in the RF record of each A Line
               - maxGain, maximum gain, in dB

        Output - self.gain, this is a linear scale gain factor
                            for each point in RF A line

        """

        super(TimeGainWidget, self).__init__(parent)

        #Store array lengths
        self.dataLength = dataLength
        self.sliderCount = sliderCount
        #Initially set unity gain
        self.gain = numpy.ones([1,dataLength])

        #Create a list of slider widgets
        self.sliderList = []
        for i in range(sliderCount):
            self.sliderList.append(QSlider(Qt.Horizontal))
            self.sliderList[i].setMinimum(0)
            self.sliderList[i].setMaximum(maxGain)
            self.sliderList[i].setValue(0)


        #--------------
        # Widget Layout
        #--------------

        VLayout = QVBoxLayout()
        #VLayout.addWidget(QLabel('Time Gain'))

        for i in range(sliderCount):
            VLayout.addWidget(self.sliderList[i])
            self.connect(self.sliderList[i], SIGNAL("sliderReleased()"), self.setGain)
            if i < sliderCount-1:
                VLayout.addStretch()

        #An extra stretch helps lines these up to the bottom of the plot
        VLayout.addStretch()
        self.setLayout(VLayout)


    def setGain(self):
        coarseGain = []
        for i in range(self.sliderCount):
            dBvalue = self.sliderList[i].value()
            Kvalue  = 10**(float(dBvalue)/20.)
            coarseGain.append(Kvalue)

        coarseList = numpy.array(range(self.sliderCount), dtype=numpy.float)
        fineList   = numpy.array(range(self.dataLength), dtype=numpy.float)
        fineList  *= float(self.sliderCount-1) / float(self.dataLength-1)

        self.gain[:] = numpy.interp(fineList,coarseList,coarseGain)

        self.emit(SIGNAL('newTimeGain'), self.gain)



class ReplayWidget(QWidget):
    def __init__(self, dataObject, parent=None):
        """
        Widget to replay a sequence of BImages as a video stream.

        Required Arguments

        dataobject:   Contains buffers and processed data.
        """
        super(ReplayWidget, self).__init__(parent)

        self.dataObject = dataObject

        self.playButton = QPushButton('Replay')
        self.stopButton = QPushButton('Stop')
        self.renderButton = QPushButton('Render')

        self.frameSlider = QSlider(Qt.Horizontal)
        self.frameSlider.setMinimum(0)
        self.frameSlider.setMaximum(self.dataObject.BVideoLength-1)
        self.frameSlider.setValue(0)


        #--------------
        # Widget Layout
        #--------------

        HLayout = QHBoxLayout()
        VLayout = QVBoxLayout()

        VLayout.addWidget(self.frameSlider)

        HLayout.addWidget(self.playButton)
        #HLayout.addStretch()
        HLayout.addWidget(self.stopButton)
        #HLayout.addStretch()
        HLayout.addWidget(self.renderButton)
        HLayout.addStretch()

        VLayout.addLayout(HLayout)

        self.setLayout(VLayout)

        #-------
        #Signals
        #-------

        self.connect(self.playButton, SIGNAL("clicked()"), self.dataObject.startBVideo)
        self.connect(self.stopButton, SIGNAL("clicked()"), self.dataObject.stopBVideo)
        self.connect(self.renderButton, SIGNAL("clicked()"), self.renderVideo)
        #Replotting is handled by parent widget, this just needs to move the slider
        self.connect(self.dataObject, SIGNAL('newBVideo'), self.updateSliderIndex)
        self.connect(self.frameSlider, SIGNAL("sliderReleased()"), self.updateVideoFrame)

    def updateSliderIndex(self, index):
        self.frameSlider.setValue(index)

    def updateVideoFrame(self):

        if self.dataObject.alive == False:
            self.dataObject.BVideoIndex = self.frameSlider.value()
            self.dataObject.emitBVideoFrame()

    def renderVideo(self):

        self.dataObject.startBVideo()
        self.dataObject.stopBVideo()

        filename = QFileDialog.getSaveFileName(self, 'Save File')

        if filename != "":

            length, height, width = self.dataObject.BVideo.shape

            video = cv2.VideoWriter(str(filename),-1,int(self.dataObject.frameRate),(width,height))

            maxVal = self.dataObject.BRange[1]

            tempFrame = numpy.zeros([height, width, 3], "uint16")

            for i in range(length):

                tempFrame[:,:,0] = self.dataObject.BVideo[i,:,:] * (2**16-1) / maxVal
                tempFrame[:,:,1] = self.dataObject.BVideo[i,:,:] * (2**16-1) / maxVal
                tempFrame[:,:,2] = self.dataObject.BVideo[i,:,:] * (2**16-1) / maxVal

                video.write(tempFrame)

            cv2.destroyAllWindows()
            video.release()





class MModeWindow(QWidget):
    def __init__(self, dataObject, parent=None):
        """
        Class contains GUI tools and layout for M mode imaging

        Required Arguments

        dataObject:  Inherits QObject. Is responsible for interfacing with
                     data acquisition hardware, data storage and memory assignment,
                     boradcasting data to main GUI, and providing physical parameters
                     related to plotting. During scanning or replay plots are updated
                     when a 'newMData' signal is recieved from the dataObject.
        """
        super(MModeWindow, self).__init__(parent)

        #-------------------
        #M mode data members
        #-------------------
        self.dataObject = dataObject

        #Scanner Micro Controller
        self.MCU = None

        #Flag to activate during scanning
        self.isScanning = False


        #------------------
        # GUI widgets setup
        #------------------

        #"Run" and "Stop" buttons
        self.runButton  = QPushButton("Scan")
        self.stopButton = QPushButton("Stop")

        #Label to report framerate
        self.frameRate = 0.0
        self.frameRateLabel = QLabel()
        self.fpsClock = time.clock

        #Analysis depth tool and setting
        self.depthPx     = dataObject.BData.shape[0]
        self.depthRange  = dataObject.getBDepth()
        self.depthArray  = numpy.linspace(self.depthRange[0],self.depthRange[1],self.depthPx)
        self.depthFocus  = dataObject.getBFocus()
        self.depthSlider = QSlider(Qt.Horizontal)
        self.depthSlider.setMinimum(0)
        self.depthSlider.setMaximum(self.depthPx-1)
        self.depthSliderIndex = int(self.depthPx*(self.depthFocus-self.depthRange[0])
                                                /(self.depthRange[1]-self.depthRange[0]))
        self.depthSlider.setValue(self.depthSliderIndex)
        self.depthValueEdit = QDoubleSpinBox()
        self.depthValueEdit.setRange(self.depthRange[0],self.depthRange[1])
        self.depthValueEdit.setSingleStep((self.depthRange[1]-self.depthRange[0])/self.depthPx)
        self.depthValueEdit.setValue(self.depthArray[self.depthSliderIndex])
        self.depthValueEdit.setSuffix(' mm')


        #M Mode display uses guiqwt.plot.ImageDialog()
        MRange = dataObject.getMTimeRange()
        BDepth = dataObject.getBDepth()
        AR = 0.4 * (MRange[1]-MRange[0]) / (BDepth[1]-BDepth[0])
        self.MDialog = ImageDialog(edit=False, toolbar=False,
                                      options=dict(title="M Sequence", \
                                                   show_contrast=False, \
                                                   aspect_ratio = AR, \
                                                   xlabel="Time Record (s)", \
                                                   ylabel="Depth (mm)", \
                                                   ysection_pos="left", \
                                                   xsection_pos="bottom", \
                                                   show_xsection=False))



        #Create a local image data array and a guiqwt.image.ImageItem
        imgyPx, imgxPx = self.dataObject.MData.shape
        self.currentMImageData = numpy.zeros([imgyPx, imgxPx])
        self.currentMImage     = make.image(self.currentMImageData, \
                                           xdata = dataObject.getMTimeRange(), \
                                           ydata = dataObject.getBDepth(), \
                                           colormap='gist_gray', \
                                           interpolation='nearest')

        imgRange = self.dataObject.getBRange()
        self.currentMImage.set_lut_range(imgRange)
        plot = self.MDialog.get_plot()
        plot.add_item(self.currentMImage)
        plot.setMaximumSize(QSize(600,300))
        plot.setMinimumSize(QSize(600,300))

        #M Mode plot depth marker
        self.depthMarkerM = make.hcursor(self.depthFocus, label=None, constraint_cb=None, movable=False, readonly=True)
        plot.add_item(self.depthMarkerM)


        #B Mode display uses guiqwt.plot.ImageDialog()
        self.BDialog = ImageDialog(edit=False, toolbar=False,
                                   options=dict(title="B Image", \
                                                show_contrast=False, \
                                                aspect_ratio = 1.00, \
                                                xlabel="Position (mm)", \
                                                ylabel="Depth (mm)", \
                                                ysection_pos="left"))

        #Create a local image data array and a guiqwt.image.ImageItem
        imgyPx, imgxPx = self.dataObject.BData.shape
        self.currentBImageData = numpy.zeros([imgxPx, imgyPx])
        self.currentBImage = make.image(self.currentBImageData, \
                                        xdata = dataObject.getBWidth(), \
                                        ydata = dataObject.getBDepth(), \
                                        colormap='gist_gray', \
                                        interpolation='nearest')

        self.currentBImage.set_lut_range(dataObject.getBRange())
        plot = self.BDialog.get_plot()
        plot.add_item(self.currentBImage)
        plot.setMaximumSize(QSize(300,300))
        plot.setMinimumSize(QSize(300,300))

        #B Mode image depth marker
        self.depthMarkerB = make.hcursor(self.depthFocus, label=None, constraint_cb=None, movable=False, readonly=True)
        plot.add_item(self.depthMarkerB)
        self.positionMarkerB = make.vcursor(0.0, label=None, constraint_cb=None, movable=False, readonly=True)
        plot.add_item(self.positionMarkerB)


        #Cross section plot
        #The same CurveDialog contains bot the time and frequency domain plots

        self.xsectionDialog = simpleCurveDialog(edit=True, toolbar=False,
                                                options=dict(xlabel=("Time Record (s)","Frequency (Hz)"), \
                                                             ylabel=("Signal (dB)", "Spectral Signal (dB)"), \
                                                             ))

        plot = self.xsectionDialog.get_plot()
        axisId = plot.get_axis_id('bottom')
        plot.set_axis_limits(axisId, dataObject.getMTimeRange()[0], dataObject.getMTimeRange()[1])
        axisId = plot.get_axis_id('left')
        plot.set_axis_limits(axisId, dataObject.getBRange()[0], dataObject.getBRange()[1])

        nativeSize = QSize(600,220)
        plot.setMaximumSize(nativeSize)
        plot.setMinimumSize(nativeSize)

        #Time domain curve - place on "left" and "bottom" axis
        xdata = self.dataObject.MTime
        ydata = self.dataObject.MTime*0
        self.xsectionCurve = make.curve(xdata, ydata, color='black', linestyle='SolidLine', linewidth=2,
                                        marker=None, markersize=5, markerfacecolor="red",
                                        markeredgecolor="black", shade=None, fitted=None,
                                        curvestyle=None, curvetype=None, baseline=None,
                                        xaxis="bottom", yaxis="left")
        plot.add_item(self.xsectionCurve)


        #Frequency curve - place on "top" and "right" axis
        """
        wdata = self.dataObject.MTime
        Ydata = self.dataObject.MTime*0
        self.xfrequencyCurve = make.curve(wdata, Ydata, color='red', linestyle='DashLine', linewidth=1,myplatform
                                          marker=None, markersize=5, markerfacecolor="red",
                                          markeredgecolor="black", shade=None, fitted=None,
                                          curvestyle=None, curvetype=None, baseline=None,
                                          xaxis="top", yaxis="right")
        plot.add_item(self.xfrequencyCurve)
        plot.enable_used_axes() #call neede to show second set of axis
        """


        #-----------
        # GUI layout
        #-----------

        grid = QGridLayout()
        row = 0


        runStopStack = QVBoxLayout()
        runStopStack.addWidget(self.runButton)
        runStopStack.addWidget(self.stopButton)
        runStopInterface = QHBoxLayout()
        runStopInterface.addLayout(runStopStack)
        runStopInterface.addStretch()
        grid.addLayout(runStopInterface, row, 0)
        row += 1


        frameRateLayout = QHBoxLayout()
        frameRateLayout.addWidget(QLabel('Frame Rate (fps): '))
        frameRateLayout.addWidget(self.frameRateLabel)
        frameRateLayout.addStretch()
        grid.addLayout(frameRateLayout, row, 0)
        row += 1


        depthLabelLayout = QHBoxLayout()
        depthLabel = QLabel('Analysis Depth:')
        depthLabelLayout.addWidget(depthLabel)
        depthLabelLayout.addWidget(self.depthValueEdit)
        depthInterface = QVBoxLayout()
        depthInterface.addLayout(depthLabelLayout)
        depthInterface.addWidget(self.depthSlider)
        depthInterfaceSpacer = QHBoxLayout()
        depthInterfaceSpacer.addLayout(depthInterface)
        depthInterfaceSpacer.addStretch(stretch=2)
        grid.addLayout(depthInterfaceSpacer,row,0)
        row += 1


        #Plotting widgets
        plotLayout = QGridLayout()
        plotLayout.addWidget(self.MDialog,0,0)
        plotLayout.addWidget(self.BDialog,0,1)
        plotLayout.addWidget(self.xsectionDialog,1,0)
        plotHSpacer = QHBoxLayout()
        plotHSpacer.addStretch()
        plotHSpacer.addLayout(plotLayout)
        plotHSpacer.addStretch()
        grid.addLayout(plotHSpacer, row, 0)
        row += 1

        self.setLayout(grid)

        #------------------
        # Signals and slots
        #------------------
        self.connect(self.depthSlider, SIGNAL("valueChanged(int)"), self.setDepthValueEdit)
        self.connect(self.depthValueEdit, SIGNAL("valueChanged(double)"), self.setDepthSlider)
        self.connect(self.runButton,  SIGNAL("clicked()"), self.runMScan)
        self.connect(self.stopButton, SIGNAL("clicked()"), self.stopMScan)
        self.connect(self.dataObject, SIGNAL("newMData"),   self.replot)
        self.connect(self.dataObject, SIGNAL("faildata"),  self.stopMScan)


    def setDepthSlider(self, depthValue):
        self.depthSliderIndex = int(self.depthPx*(depthValue-self.depthRange[0])
                                                /(self.depthRange[1]-self.depthRange[0]))
        self.depthSlider.setValue(self.depthSliderIndex)
        self.depthMarkerB.set_pos(y=depthValue)
        self.depthMarkerM.set_pos(y=depthValue)
        if self.isScanning == False:
            dataPackage = (self.currentBImageData,self.currentMImageData)
            self.replot(dataPackage, setFrameRate=False)


    def setDepthValueEdit(self, sliderIndex):
        self.depthSliderIndex = sliderIndex
        self.depthValueEdit.setValue(self.depthArray[sliderIndex])
        self.depthMarkerB.set_pos(y=self.depthArray[sliderIndex])
        self.depthMarkerM.set_pos(y=self.depthArray[sliderIndex])
        if self.isScanning == False:
            dataPackage = (self.currentBImageData,self.currentMImageData)
            self.replot(dataPackage, setFrameRate=False)

    def runMScan(self):
        """ Method contains program loop to acquire and plot B mode images """

        self.isScanning = True
        self.plotsReady = True

        if self.MCU is not None:
            self.MCU.setAC()

        #Calculate display frame rate
        self.preClock = self.fpsClock()

        #Start data collection
        self.dataObject.setMMode()
        self.dataObject.collect()


    def stopMScan(self):

        try:
            self.dataObject.alive = False
        except:
            pass

        if self.MCU is not None:
            self.MCU.setDC()

        self.isScanning = False


    def replot(self, dataPackage, setFrameRate=True):

        #Unpack data from the tuple
        BImageData = dataPackage[0]
        MImageData = dataPackage[1]

        #Replot M-Mode
        self.currentMImageData = MImageData
        self.currentMImage.set_data(MImageData)
        plot = self.MDialog.get_plot()
        plot.replot()

        #Replot the B-Mode
        self.currentBImageData = BImageData
        self.currentBImage.set_data(BImageData)
        plot = self.BDialog.get_plot()
        plot.replot()

        #When replot is called from the scan method the frame
        #rate should be updated. When a redraw is needed by a slider
        #depth update the frame rate should not be changed.
        if setFrameRate == True:
            self.curClock = self.fpsClock()
            self.frameRate = 1.0 / ( self.curClock-self.preClock)
            self.frameRateLabel.setText('{:.1f}'.format(self.frameRate))
            self.preClock = self.curClock

        #Get cross section data for time series and FFT
        tData = self.dataObject.MTime
        xData = self.currentMImageData[self.depthSlider.value(),:]
        self.xsectionCurve.set_data(tData, xData)

        #Frequency analysis not needed in MMode
        #wData, XData = frequencySpectrum(tData, xData, timebase=1.0)
        #self.xfrequencyCurve.set_data(wData, XData)

        plot = self.xsectionDialog.get_plot()
        plot.replot()


    def setMCU(self, MCU):
        self.MCU = MCU



class RFWindow(QWidget):

    def __init__(self, dataObject, parent=None):
        """
        Class contains GUI tools and layout for RF data display

        Required Arguments

        dataObject:  Inherits QObject. Is responsible for interfacing with
                     data acquisition hardware, data storage and memory assignment,
                     boradcasting data to main GUI, and providing physical parameters
                     related to plotting. During scanning or replay plots are updated
                     when a 'newRFData' signal is recieved from the dataObject.
        """
        super(RFWindow, self).__init__(parent)

        #-------------------
        #RF mode data members
        #-------------------
        self.dataObject = dataObject
        self.dataObject.setRF()


        #------------------
        # GUI widgets setup
        #------------------

        #Set "Run" and "Stop" buttons in horizontal layout
        self.runButton  = QPushButton("Scan")
        self.stopButton = QPushButton("Stop")


        #Label to report framerate
        self.frameRate = 0.0
        self.frameRateLabel = QLabel()
        self.fpsClock = time.clock

        frameRateLayout = QHBoxLayout()
        frameRateLayout.addWidget(QLabel('Frame Rate (fps): '))
        frameRateLayout.addWidget(self.frameRateLabel)
        frameRateLayout.addStretch()


        #Label to report signal rms
        self.Vrms = 0.0
        self.VrmsLabel = QLabel()

        VrmsLayout = QHBoxLayout()
        VrmsLayout.addWidget(QLabel('Signal (mVrms): '))
        VrmsLayout.addWidget(self.VrmsLabel)
        VrmsLayout.addStretch()


        #Time domain plot using a guiqwt.plot.CurveDialog
        self.plotDialog = simpleCurveDialog(edit=True, toolbar=True,
                                            options=dict(xlabel="Time (s)", ylabel="Signal (mV)"))

        plot = self.plotDialog.get_plot()
        axisId = plot.get_axis_id('bottom')
        tRange = dataObject.getRFTimeRange()
        plot.set_axis_limits(axisId, tRange[0], tRange[1])
        axisId = plot.get_axis_id('left')
        vRange = dataObject.getRFmVRange()
        plot.set_axis_limits(axisId, vRange[0], vRange[1])

        xRF = self.dataObject.RFData[0,:]
        yRF = self.dataObject.RFData[1,:]
        self.RFCurve = make.curve(xRF, yRF, color='black', linestyle='SolidLine', linewidth=1,
                                  marker=None, markersize=5, markerfacecolor="red",
                                  markeredgecolor="black", shade=None, fitted=None,
                                  curvestyle=None, curvetype=None, baseline=None,
                                  xaxis="bottom", yaxis="left")
        plot.add_item(self.RFCurve)


        #Frequency domain plot using a guiqwt.plot.CurveDialog
        self.powerDialog = simpleCurveDialog(edit=True, toolbar=True,
                                            options=dict(xlabel="Frequency (MHz)", \
                                                         ylabel="Signal Power (mV/Hz)"))

        plot = self.powerDialog.get_plot()
        axisId = plot.get_axis_id('bottom')
        plot.set_axis_limits(axisId, 0, 100)
        #allow yaxis to autoscale

        wRF, pRF = frequencySpectrum(xRF, yRF)
        self.powerCurve = make.curve(wRF, pRF, color='black', linestyle='SolidLine', linewidth=1,
                                     marker=None, markersize=5, markerfacecolor="red",
                                     markeredgecolor="black", shade=None, fitted=None,
                                     curvestyle=None, curvetype=None, baseline=None,
                                     xaxis="bottom", yaxis="left")
        plot.add_item(self.powerCurve)


        #-----------
        # GUI layout
        #-----------

        grid = QGridLayout()
        row = 0

        runStopStack = QVBoxLayout()
        runStopStack.addWidget(self.runButton)
        runStopStack.addWidget(self.stopButton)
        runStopInterface = QHBoxLayout()
        runStopInterface.addLayout(runStopStack)
        runStopInterface.addStretch()
        grid.addLayout(runStopInterface, row, 0)
        row += 1

        grid.addLayout(frameRateLayout, row, 0)
        row += 1

        grid.addLayout(VrmsLayout, row, 0)
        row += 1

        grid.addWidget(self.plotDialog, row, 0)
        row += 1

        grid.addWidget(self.powerDialog, row, 0)
        row += 1
        self.setLayout(grid)

        #------------------
        # Signals and slots
        #------------------

        self.connect(self.runButton,  SIGNAL("clicked()"), self.runRFScan)
        self.connect(self.stopButton, SIGNAL("clicked()"), self.stopRFScan)
        self.connect(self.dataObject, SIGNAL("newRFData"), self.replot)
        self.connect(self.dataObject, SIGNAL("faildata"),  self.stopRFScan)

    def runRFScan(self):
        """ Start the thread containing the data acquisition loop """

        #Calculate display frame rate
        self.preClock = self.fpsClock()

        #Start data collection
        self.dataObject.setRF()
        self.dataObject.collect()


    def stopRFScan(self):
        try:
            self.dataObject.alive = False
        except:
            pass


    def replot(self, RFData):

        self.RFCurve.set_data(RFData[0,:], RFData[1,:])
        plot = self.plotDialog.get_plot()
        plot.replot()

        self.curClock = self.fpsClock()
        self.frameRate = 1.0 / ( self.curClock-self.preClock)
        self.frameRateLabel.setText('{:.1f}'.format(self.frameRate))
        self.preClock = self.curClock

        #Compute signal RMS
        Vrms = numpy.sqrt(numpy.average(RFData[1,:]*RFData[1,:]))
        self.VrmsLabel.setText('{:.2f}'.format(Vrms))

        #Compute power spectrum
        w, P = frequencySpectrum(RFData[0,:], RFData[1,:])
        self.powerCurve.set_data(w, P)
        plot = self.powerDialog.get_plot()
        plot.replot()
        #plot.do_autoscale()


    def setMCU(self, MCU):
        self.MCU = MCU



class simpleCurveDialog(CurveDialog):
    """
    Method override to remove "OK" & "Cancel" buttons
    from the GUIQWT CurveDialog class
    """
    def install_button_layout(self):
        pass


class HiFUSData(QObject):

    def __init__(self, parent=None, UseOCL=USEOCL):
        """

        """
        super(HiFUSData, self).__init__(parent)

        self.alive  = False
        self.emitB  = False
        self.emitM  = False
        self.emitRF = False

        #------------------------------
        #Setup acqusition buffers
        #------------------------------

        #TO DO: get these parameters from a configuration file
        bufferCnt=20
        recordCnt=100
        sampleCnt=4160
        DAQ.SetBufferRecordSampleCount(bufferCnt,recordCnt,sampleCnt)

        trigDelay = 6.0E-03*(2.0/1500.)
        DAQ.SetTriggerDelaySec(trigDelay)

        #Store settings
        self.numBuffers   = bufferCnt
        self.recordCnt    = recordCnt
        self.recordLength = sampleCnt

        #Handle to acquisition board
        self.boardHandle = DAQ.GetBoardHandle(1,1)

        #Acquisition sample rate
        self.sampleRate  = DAQ.GetSampleRate()

        #Acquisition frame rate
        #This is a nominal value, and should come from a configuration file
        self.frameRate     = 95.0;

        #Memory buffers
        self.bufIndex = 0
        self.bufPerAcq   = 1
        self.numBuffers  = bufferCnt
        self.lenBuffers  = DAQ.GetBufferLength()
        self.buffers     = numpy.empty([self.numBuffers,self.lenBuffers], dtype=numpy.uint16, order='C')
        self.bufferCheck = DAQ.CheckBufferSize(self.boardHandle, self.buffers)

        #Create shared array for child process, 'H' designates unsigned short
        self._shBuffersArr = multiprocessing.Array('H',self.buffers.size)
        self.shBuffers     = numpy.frombuffer(self._shBuffersArr.get_obj(),dtype='H')
        self.shBuffers     = self.shBuffers.reshape(self.buffers.shape,order='C')

        #Temporary demodulated/envelope data array
        self.decimation  = DAQ.GetDecimation()
        self.envData     = numpy.empty([1,self.lenBuffers/self.decimation], \
                                        dtype=numpy.double, order='C')

        #BMode data
        self.BLength = self.recordLength / self.decimation
        self.BLines  = self.recordCnt
        self.BData   = numpy.zeros([self.BLength,self.BLines], dtype=numpy.double)

        self._shBDataArr = multiprocessing.Array('d',self.BData.size)
        self.shBData     = numpy.frombuffer(self._shBDataArr.get_obj(),dtype='d')
        self.shBData     = self.shBData.reshape(self.BData.shape,order='C')

        self.BVideoLength = 5*self.frameRate
        self.BVideo = numpy.zeros([self.BVideoLength, self.BLength, self.BLines], dtype=numpy.double)
        self.BVideoIndex = 0
        self.BVideoTimer = QTimer()
        self.BVideoTimer.setInterval(int(1000./self.frameRate))
        self.connect(self.BVideoTimer, SIGNAL("timeout()"), self.emitBVideoFrame)

        self._shBVideoArr = multiprocessing.Array('d',self.BVideo.size)
        self.shBVideo     = numpy.frombuffer(self._shBVideoArr.get_obj(),dtype='d')
        self.shBVideo     = self.shBVideo.reshape(self.BVideo.shape,order='C')

        #BMode physical parameters
        #TODO: These should come from a configuration file
        self.BDepth  = [6.0, 6.0+1000*0.5*1500*((self.BLength-1)*self.decimation/self.sampleRate)]
        self.BWidth  = [-3.0, 3.0]
        self.BFocus  = 7.0
        self.BRange  = [0, 60]

        #BMode frame averaging
        self.BAverage = 1

        #Time Gain
        self.timeGain = numpy.ones([1,DAQ.GetRecordLength()], dtype=numpy.double)
        self._shTimeGainArr = multiprocessing.Array('d',self.timeGain.size)
        self.shTimeGain     = numpy.frombuffer(self._shTimeGainArr.get_obj(),dtype='d')
        self.shTimeGain     = self.shTimeGain.reshape(self.timeGain.shape,order='C')
        self.shTimeGain[:] = self.timeGain[:]

        #M Mode
        self.MRecordLength = 256
        self.MData = numpy.zeros([self.BLength, self.MRecordLength], dtype=numpy.double)
        self.MTime = numpy.linspace(0, (self.MRecordLength-1)/self.frameRate, self.MRecordLength)

        self._shMDataArr = multiprocessing.Array('d',self.MData.size)
        self.shMData     = numpy.frombuffer(self._shMDataArr.get_obj(),dtype='d')
        self.shMData     = self.shMData.reshape(self.MData.shape,order='C')


        #RF data output
        self.RFRecordLength = DAQ.GetRecordLength()
        self.RFData         = numpy.zeros([2,self.RFRecordLength], dtype=numpy.double)
        self.RFTimeRange    = [4.0E-06, 4.0E-06+(self.RFRecordLength-1)/self.sampleRate]
        self.RFData[0,:]    = numpy.linspace(self.RFTimeRange[0], self.RFTimeRange[1], self.RFRecordLength)
        self.RFDataStart    = (self.recordCnt/2)*self.RFRecordLength-1
        self.RFDataStop     = self.RFDataStart + self.RFRecordLength
        self.RFSignalRange  = [-0.400, 0.400]

        self._shRFDataArr = multiprocessing.Array('d',self.RFData.size)
        self.shRFData     = numpy.frombuffer(self._shRFDataArr.get_obj(),dtype='d')
        self.shRFData     = self.shRFData.reshape(self.RFData.shape,order='C')
        self.shRFData[:]  = self.RFData[:]


        #Start a child process to handle the actual data collection
        if MULTIPROCESS == True:
            self.parentSocket, self.childSocket = multiprocessing.Pipe()
            self.childProcess = multiprocessing.Process(target=CollectProcess, \
                                                        args=[self.childSocket, \
                                                              self._shBuffersArr, self.buffers.shape, \
                                                              self._shTimeGainArr,self.timeGain.shape, \
                                                              self._shBDataArr,   self.BData.shape, \
                                                              self._shBVideoArr,  self.BVideo.shape, \
                                                              self._shMDataArr,   self.MData.shape, \
                                                              self._shRFDataArr,  self.RFData.shape,
                                                              bufferCnt, recordCnt, sampleCnt, trigDelay])


            self.childProcess.daemon=True
            self.childProcess.start()
            #use a blocking receive to wait for the process to start
            #this only happens once when the GUI is loaded
            procResult = self.parentSocket.recv()
        #end MULTIPROCESS == True

        #Optional OpenCL for GPU based processing
        self.useCL = False
        if UseOCL:
            self._initCL()
        pass

    def setBMode(self):
        self.emitB  = True
        self.emitM  = False
        self.emitRF = False

    def setMMode(self):
        self.emitB  = False
        self.emitM  = True
        self.emitRF = False

    def setRF(self):
        self.emitB  = False
        self.emitM  = False
        self.emitRF = True

    def getBWidth(self):
        return self.BWidth

    def getBDepth(self):
        return self.BDepth

    def getBRange(self):
        """Report the maximum BMode signal range (dB scale)"""
        return self.BRange

    def getBFocus(self):
        return self.BFocus

    def getMTimeRange(self):
        return [numpy.min(self.MTime),numpy.max(self.MTime)]

    def getRFTimeRange(self):
        return self.RFTimeRange

    def getRFmVRange(self):
        mVmin = self.RFSignalRange[0]*1000
        mVmax = self.RFSignalRange[1]*1000
        return [mVmin,mVmax]

    def setBAverage(self, n):
        self.BAverage = n
        if MULTIPROCESS == True:
            #send for data
            self.parentSocket.send('BAverage')
            #Wait for reply, process GUI events while waiting
            self.parentSocket.recv()
            #Tell child OK to resume with new value
            self.parentSocket.send(str(n))

        if self.alive != True:
            DAQ.IQDemodulateAvg(self.buffers, self.envData, self.bufIndex-1, \
                                average=self.BAverage, gain=self.timeGain)
            dataToBMode(self.envData, self.BData, self.BLength, self.BLines)
            self.emit(SIGNAL('newBData'), self.BData)

    def setTimeGain(self, timeGain):
        self.timeGain[:] = timeGain[:]
        if MULTIPROCESS == True:
            #Tell process the timeGain array needs updating
            self.parentSocket.send('timeGain')
            #Wait for reply of message received
            self.parentSocket.recv()
            #Update the shared array
            self.shTimeGain[:] = self.timeGain[:]
            #Send message to resume
            self.parentSocket.send(True)

        if self.alive != True:
            self.processBData()
            self.emit(SIGNAL('newBData'), self.BData)

    def getCurrentBuffer(self):
        #TODO: this method needs updating / is redundant
        #As full data set is shared when live scanning
        #is stopped.
        if MULTIPROCESS == True:
            #if multi processing we need to request buffer data
            self.parentSocket.send('shareBuffer')
            #Poll for reply, process GUI events while waiting
            while(self.parentSocket.poll() == False):
                QApplication.processEvents()
            curIndex = self.parentSocket.recv()
            #OK to copy shared array back to local array
            self.buffers[:] = self.shBuffers[:]
            #Tell child OK to resume
            self.parentSocket.send(True)
            return numpy.array(self.buffers[curIndex,:])

        else:
            return numpy.array(self.buffers[self.bufIndex-1,:])


    def collect(self):
        if MULTIPROCESS == True:
            self._collectMP()
        else:
            self._collectSP()

    def startBVideo(self):
        self.BVideo = numpy.roll(self.BVideo[:], -int(self.BVideoIndex), axis=0)
        self.BVideoIndex = 0
        self.BVideoTimer.start()

    def emitBVideoFrame(self):
        BData = self.BVideo[self.BVideoIndex,:,:]
        self.emit(SIGNAL('newBData'), BData)
        self.emit(SIGNAL('newBVideo'), self.BVideoIndex)
        self.BVideoIndex += 1
        self.BVideoIndex = self.BVideoIndex % self.BVideoLength

    def stopBVideo(self):
        self.BVideoTimer.stop()
        self.BVideoIndex = 0

    def processBData(self):
        if self.useCL:
            self._clIQDemodulateAvg()
        else:
            DAQ.IQDemodulateAvg(self.buffers, self.envData, self.bufIndex-1, average=self.BAverage, gain=self.timeGain)
        dataToBMode(self.envData, self.BData, self.BLength, self.BLines)

    def _initCL(self):
        #Check openCL version
        try:
            clv = cl.VERSION_TEXT
            if not clv =="2013.1":
                raise Exception('Update your PyOpenCL version to 2013.1!' )
        except:
            raise Exception('Please install PyOpenCL or set UseOpenCL=False !' )
        del clv
        
        # create an OpenCL context
        myplatform = cl.get_platforms()
        mygpudevices = myplatform[0].get_devices(device_type=cl.device_type.GPU)
        self.clCtx = cl.Context(devices = mygpudevices)
        self.clQueue = cl.CommandQueue(self.clCtx)
        self.clLoadProgram("IQDemod.cl")

        self.useCL = True
        
        mf = cl.mem_flags

        #Create OpenCL arrays
        
        self._clBuffers = cl.Buffer(self.clCtx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=self.buffers)
        self._clEnvData = cl.Buffer(self.clCtx, mf.WRITE_ONLY, self.envData.nbytes)
        self._clTimeGain = cl.Buffer(self.clCtx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=numpy.array(self.timeGain, dtype=numpy.double))

        DAQParams = numpy.array([self.numBuffers, self.lenBuffers, self.recordCnt, self.recordLength], dtype=numpy.int)
        self.DAQParams_buf = cl.Buffer(self.clCtx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=DAQParams)

        # Define OCL Parameters [BufferIndex, NumAverage, UseGain, Decimate]
        self.OCLParams = numpy.array([self.bufIndex-1, self.BAverage, True, self.decimation], dtype=numpy.int)
        self.OCLParams_buf = cl.Buffer(self.clCtx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=self.OCLParams)
        self.clThreads = (self.lenBuffers / self.decimation, 1)

    def _clIQDemodulateAvg(self):
        cl.enqueue_write_buffer(self.clQueue, self._clBuffers, self.buffers)
        #TODO Can we just update one part of the buffer (The written to parts, instead of copying entire buffer.)
        cl.enqueue_write_buffer(self.clQueue, self._clTimeGain, self.timeGain)
        self.OCLParams[0] = (self.bufIndex-1)
        #print time.time(), self.OCLParams[0]
        self.OCLParams[1] = self.BAverage
        cl.enqueue_write_buffer(self.clQueue, self.OCLParams_buf, self.OCLParams).wait()

        Event = self.program.iqDemodAvg(self.clQueue, self.clThreads, None, self._clBuffers, self._clEnvData, self._clTimeGain, self.OCLParams_buf, self.DAQParams_buf)
        Event.wait()
        IQData = numpy.empty(self.envData.size, self.envData.dtype)
        cl.enqueue_copy(self.clQueue, IQData, self._clEnvData)

        self.envData = numpy.reshape(IQData, self.envData.shape)

    def clLoadProgram(self, filename):
        #read in the OpenCL source file as a string
        f = open(filename, 'r')
        fstr = "".join(f.readlines())
        #create the program
        self.program = cl.Program(self.clCtx, fstr).build()


    def _collectSP(self):

        #Check to verify the buffers were properly configured
        if self.bufferCheck != True:
            print 'bufferCheck fail'
            return

        #Configure the DAQ board
        self.configResult = DAQ.ConfigureBoard(self.boardHandle)
        if self.configResult != True:
            print 'Config fail'
            return

        #Post buffers to aquisition board
        postResult = DAQ.PostBuffers(self.boardHandle, self.buffers)
        if postResult != True:
            print 'Post fail'
            return

        acquireData = DAQ.AcquireBuffers
        self.bufIndex = 0
        self.BVideoIndex = 0
        bufIndex  = self.bufIndex
        bufPerAcq = self.bufPerAcq

        self.alive = True
        while(self.alive):
            acquireResult = acquireData(self.boardHandle, self.buffers, bufIndex, bufPerAcq)
            if acquireResult != True:
                print 'Acquire fail'
                self.alive = False
                self.emit(SIGNAL('faildata'))
                continue
            bufIndex += bufPerAcq
            bufIndex  = bufIndex % self.numBuffers
            self.bufIndex = bufIndex

            #Emit signal to replot in main GUI, provide data as argument
            if self.emitB == True:
                self.processBData()
                self.BVideo[self.BVideoIndex,:,:] = self.BData[:,:]
                self.BVideoIndex += 1
                self.BVideoIndex = self.BVideoIndex % self.BVideoLength
                self.emit(SIGNAL('newBData'), self.BData)

            if self.emitM == True:
                self.processBData()
                self.MData = numpy.roll(self.MData, 1)
                self.MData[:,0] = self.BData[:,self.BLines/2-1]
                dataPackage = self.BData, self.MData
                self.emit(SIGNAL('newMData'), dataPackage)

            if self.emitRF == True:
                self.RFData[1,:] = self.buffers[bufIndex-1, self.RFDataStart:self.RFDataStop]*1.2210012210012e-02 - 398.73
                self.emit(SIGNAL('newRFData'), self.RFData)

            QApplication.processEvents()

        else:
            DAQ.StopAcquisition(self.boardHandle)
            return

    def _collectMP(self):
        """ Run data collection using a child process """

        #Check that the child process is running
        #if self.childProcess.is_alive() is not True:
        #    print self.childProcess.is_alive()
        #    self.emit(SIGNAL('stopped'))
        #    return False

        #Bring the child process out of the idle loop
        self.parentSocket.send('scan')
        while(self.parentSocket.poll() == False):
            QApplication.processEvents()
        self.parentSocket.recv()


        self.alive = True
        while(self.alive):

            if self.emitB == True:
                #send for data
                self.parentSocket.send('BData')
                #Poll for reply, process GUI events while waiting
                #while(self.parentSocket.poll() == False):
                    #QApplication.processEvents()
                self.parentSocket.recv()
                #copy shared array back to local array
                self.BData[:] = self.shBData[:]
                #Tell child OK to resume
                self.parentSocket.send(True)
                #emit the new data to the replot function
                self.emit(SIGNAL('newBData'), self.BData)

            if self.emitM == True:
                #send for data
                self.parentSocket.send('MData')
                #Poll for reply, process GUI events while waiting
                #while(self.parentSocket.poll() == False):
                    #QApplication.processEvents()
                self.parentSocket.recv()
                #copy shared array back to local array
                self.BData[:] = self.shBData[:]
                self.MData[:] = self.shMData[:]
                #Tell child OK to resume
                self.parentSocket.send(True)
                #emit the new data to the replot function
                dataPackage = self.BData, self.MData
                self.emit(SIGNAL('newMData'), dataPackage)

            if self.emitRF == True:
                #send for data
                self.parentSocket.send('RFData')
                #Poll for reply, process GUI events while waiting
                #while(self.parentSocket.poll() == False):
                    #QApplication.processEvents()
                self.parentSocket.recv()
                #copy shared array back to local array
                self.RFData[:] = self.shRFData[:]
                #Tell child OK to resume
                self.parentSocket.send(True)
                #emit the new data to the replot function
                self.emit(SIGNAL('newRFData'), self.RFData)

            QApplication.processEvents()

        else:
            self.parentSocket.send('idle')
            while(self.parentSocket.poll() == False):
                QApplication.processEvents()
            self.bufIndex = self.parentSocket.recv()                   
            self.emit(SIGNAL('stopped'))
            #Update all local arrays from shared arrays
            self.buffers[:] = self.shBuffers[:]
            self.BData[:] = self.shBData[:]
            self.BVideo[:] = self.shBVideo[:]
            #Need to know the BVideoIndex
            self.parentSocket.send('BVideo')
            self.BVideoIndex = int(self.parentSocket.recv())
            self.parentSocket.send(True)
            self.MData[:] = self.shMData[:]
            self.RFData[:] = self.shRFData[:]

    def terminate(self):
        """
        Clean up method incase user exits parent application
        during data acqusisiton.
        """
        stopped = False


        if MULTIPROCESS == True:
            #Attempt to stop collection process
            self.parentSocket.send('stop')
            time.sleep(0.5)
            #Check if the process is actually stopped
            if self.childProcess.is_alive() == True:
                #The process hasn't ended gracefully
                #Time for a heavy hand...
                self.childProcess.terminate()
            else:
                stopped = True

        return stopped



def CollectProcess(childSocket, \
                         _shBuffersArr, buffersShape, \
                         _shGainArr,    gainShape, \
                         _shBDataArr,   BDataShape, \
                         _shBVideoArr,  BVideoShape, \
                         _shMDataArr,   MDataShape, \
                         _shRFDataArr,  RFDataShape, \
                         bufferCnt, recordCnt, sampleCnt, trigDelay):
    """
    Unbound function to be run as a child process handling data acquisiton
    Function is set up as a pseudo event loop that polls for instructions
    """

    #Give the shared arrays local numpy array references
    buffers = numpy.frombuffer(_shBuffersArr.get_obj(),dtype='H')
    buffers = buffers.reshape(buffersShape,order='C')

    gain = numpy.frombuffer(_shGainArr.get_obj(),dtype='d')
    gain = gain.reshape(gainShape,order='C')

    BData = numpy.frombuffer(_shBDataArr.get_obj(),dtype='d')
    BData = BData.reshape(BDataShape,order='C')

    BVideo = numpy.frombuffer(_shBVideoArr.get_obj(),dtype='d')
    BVideo = BVideo.reshape(BVideoShape,order='C')

    MData = numpy.frombuffer(_shMDataArr.get_obj(),dtype='d')
    MData = MData.reshape(MDataShape,order='C')

    RFData = numpy.frombuffer(_shRFDataArr.get_obj(),dtype='d')
    RFData = RFData.reshape(RFDataShape,order='C')


    #Send a message to the parent to indicate the process has started
    childSocket.send(True)
    alive = True
    idle = True

    #Configure the record size
    DAQ.SetBufferRecordSampleCount(bufferCnt,recordCnt,sampleCnt)
    boardHandle = DAQ.GetBoardHandle(1,1)
    DAQ.SetTriggerDelaySec(trigDelay)
    acquireData = DAQ.AcquireBuffers


    #A few constants and derivatives from the input arrays
    BLength, BLines = BData.shape
    RFStart = (recordCnt/2)*sampleCnt - 1
    RFStop  = RFStart + sampleCnt

    bufIndex = 0
    bufPerAcq = 1

    BAverage = 1
    envData = numpy.empty([1,BData.size], dtype=numpy.double, order='C')

    BVideoLength = BVideoShape[0]
    BVideoIndex = 0

    while(alive):

        while idle == True:
            #The routine just sleeps and polls for instrucitons
            time.sleep(0.1)
            if childSocket.poll() == True:
                message = childSocket.recv()

                #Request to share buffer data
                if message == 'shareBuffer':
                    #Confirm request received
                    childSocket.send(bufIndex-1)
                    #Wait for command to resume
                    childSocket.recv()

                #Update number of frames to average during BMode
                elif message == 'BAverage':
                    #Confirm request received
                    childSocket.send(True)
                    #Wait for command to resume
                    BAverage = int(childSocket.recv())

                #Request to update the time gain curve used
                elif message == 'timeGain':
                    #Confirm request received
                    childSocket.send(True)
                    #Wait for command to resume
                    childSocket.recv()

                #Request to report the BVideo frame index
                elif message == 'BVideo':
                    #Confirm request received
                    childSocket.send(BVideoIndex)
                    #Wait for command to resume
                    childSocket.recv()

                #Exiting the idle.
                elif message == 'scan':

                    idle = False

                    #Setup the DAQ board
                    configResult = DAQ.ConfigureBoard(boardHandle)
                    if configResult != True:
                        childSocket.send('Config fail')
                        return

                    #Post buffers to DAQ board
                    postResult = DAQ.PostBuffers(boardHandle, buffers)
                    if postResult != True:
                        childSocket.send('Post fail')
                        return

                    bufIndex = 0
                    BVideoIndex = 0

                    #post to indicate the child process has exited idle
                    childSocket.send('exitIdle')

                else:
                    #If the recieved code is nonsense end the loop
                    #This kills the process
                    DAQ.StopAcquisition(boardHandle)
                    alive = False
                    childSocket.send(False)


        #Acquire new data from the DAQ
        acquireResult = acquireData(boardHandle, buffers, bufIndex, bufPerAcq)
        if acquireResult != True:
            childSocket.send('Acquire fail')
            self.alive = False
            return

        #if BAverage > 1:
        DAQ.IQDemodulateAvg(buffers, envData, bufIndex, BAverage, gain)
        dataToBMode(envData, BData, BLength, BLines)

        BVideo[BVideoIndex,:,:] = BData[:,:]
        BVideoIndex += 1
        BVideoIndex = BVideoIndex % BVideoLength

        MData[:] = numpy.roll(MData, 1)
        MData[:,0] = BData[:,BLines/2-1]
        RFData[1,:] = buffers[bufIndex, RFStart:RFStop]*1.2210012210012e-02 - 398.7
        bufIndex += bufPerAcq
        bufIndex  = bufIndex % bufferCnt

        #Check if the parent wants new data
        #Optional frame skip incase display can't keep up with processing
        if (bufIndex%2 == 0):
            if childSocket.poll() == True:
                cmd = childSocket.recv()
                #First populate the shared array with new data
                #then send a message to indicate the shared array is updated

                if cmd == 'BData':
                    #Confirm request recieved
                    childSocket.send('BData')
                    #Wait for command to resume
                    childSocket.recv()

                #Update number of frames to average during BMode
                elif cmd == 'BAverage':
                    #Confirm request received
                    childSocket.send('BAverage')
                    #Wait for command to resume
                    BAverage = int(childSocket.recv())

                #Request to update the time gain curve used
                elif cmd == 'timeGain':
                    #Confirm request received
                    childSocket.send(True)
                    #Wait for command to resume
                    childSocket.recv()

                elif cmd == 'MData':
                    #Confirm request recieved
                    childSocket.send('MData')
                    #Wait for command to resume
                    childSocket.recv()

                elif cmd == 'RFData':
                    #Confirm request recieved
                    childSocket.send('RFData')
                    #Wait for command to resume
                    childSocket.recv()

                elif cmd == 'idle':
                    DAQ.StopAcquisition(boardHandle)
                    idle = True
                    #Send back the bufIndex to the parent so that
                    #it knows what the the most recent data is
                    childSocket.send(bufIndex)

                else:
                    #If the recieved code is nonsense end the loop
                    #This kills the process
                    DAQ.StopAcquisition(boardHandle)
                    alive = False
                    childSocket.send(False)


class DummyHardware(object):

    #Class members represent configuraiton options on DAQ hardware
    bytesPerSample = 2
    decimation = 10
    bufferCnt=20
    recordCnt=100
    sampleCnt=5120
    chanCnt=1
    sampleRate=500.0E+06
    triggerDelay = 0.0

    def __init__(self, parent= None):
        """
        DummyHardware

        This class is a template for writing DAQ hardware wrappers.
        By following this template new hardware can be used
        with OpenHiFUS without additional changes to the application.
        Each method in the DummyHardware is intended to call similar
        functionality in a hardware DAQ driver. DAQ drivers can be
        accessed using pythons ctypes module, or can be compiled as
        native extensions using pythons c language api.
        """
        pass


    def SetBufferRecordSampleCount(self,bufferCnt,recordCnt,sampleCnt):
        """
        DummyHardware.SetBufferRecordSampleCount(...)

        A memory buffer corresponds to a complete RF data set for B mode image.
        Each buffer contains a specified number of records. A record corresponds
        to an "A" line of the image. The DAQ hardware should record the
        specified number of samples in each A line after a hardware trigger.

        Parameters: bufferCnt (int), the number of RF comple RF data frames
                                     to store.

                    recordCnt (int), the number of records (A lines) per image.

                    sampleCnt (int), the length of each recorded record (A line).
        """

        self.bufferCnt = bufferCnt
        self.recordCnt = recordCnt
        self.sampleCnt = sampleCnt


    def GetBoardHandle(self, sysId=1, boardId=1):
        """
        DummyHardware.GetBoardHandle(...)

        Hardware will typically have an address in system memory that is used
        as an identifier for interface software. This can also be know as a
        memory handle. In systems with with multiple groupings of hardware, each
        containg multiple DAQ cards, it may be necessary to specify which card
        is to be used. Even in single DAQ card systems it is often still necessary
        to obtain this memory handle.

        For the DummyHardware class there is no real hardware connected, so the
        returned object can be anything. When interfacing with actual hardware,
        the returned object should be a PyCapsul object, which is a python container
        for a c-style memory pointer (* void).

        Parameters: sysId (int), the DAQ system number on a PC containg multiple
                                 groups of DAQ cards.
                    boardId (int), the DAQ card number within the specified system

        """

        return 1


    def GetSampleRate(self):
        """
        DummyHardware.GetSampleRate()

        Reports the hardware setting for acquisition sample rate.
        Sample rate is typically fixed for a particular application.
        Currently hardware sample rates cannot be adjusted from OpenHiFUS,
        instead the sample rate should be directly set using hardware
        drivers.
        TODO: Add methods to adjust sample rate

        Parameters: None

        Returns: sampleRate
        """

        return self.sampleRate


    def GetBufferLength(self):
        """
        DummyHardware.GetBufferLength()

        Reports the length (number of values) in each memory buffer.
        The reported length accounts for the current record count,
        sample count, and channel count settings.

        Parameters: None

        Returns: Required buffer length for current hardware settings.
        """

        bufferLength = self. chanCnt * self.recordCnt * self.sampleCnt

        return bufferLength


    def CheckBufferSize(self, boardHandle, buffers):
        """
        DummyHardware.CheckBufferSize(...)

        A helper function to prevent errors when using python allocated
        arrays as memory buffers. The size of the buffer arrays (in bytes)
        is checked against an expected value based on hardware settings.

        Parameters: boardhandle, python object containg the DAQ card
                                 memory handle

                    buffers, the numpy array containg all acqusition buffers

        Returns: True on successful test

        """

        memSize = buffers.nbytes

        expectedSize = self.chanCnt * \
                       self.bufferCnt * \
                       self.recordCnt * \
                       self.sampleCnt * \
                       self.bytesPerSample

        test = (memSize == expectedSize)

        return test

    def GetDecimation(self):
        """
        DummyHardware.GetDecimation()

        Reports the decimation factor between aquired high frequency
        data and processed (envelope) data. Decimation factor is
        currently fixed in the hardware wrapper.
        TODO: Allow setting decimation from OpenHiFUS

        Parameters: None

        Returns: decimation (int)
        """

        return self.decimation

    def GetRecordLength(self):
        """
        DummyHardware.GetRecordLength()

        Report the current setting for samples per record (A scan)

        Parameters: None

        Returns: recordLength (int)
        """

        recordLength = self.sampleCnt
        return recordLength


    def ConfigureBoard(self, boardHandle):
        """
        DummyHardware.ConfigureBoard(...)

        Placeholder method. With actual hardware this method is
        used to apply all specified hardware settings (sample count,
        channel count, trigger delay, ect.) prior to starting an
        acquisition sequence.

        Parameters: boardhandle, python object containg the DAQ card
                                 memory handle

        Returns: True on success
        """

        return True

    def PostBuffers(self, boardHandle, buffers):
        """
        DummyHardware.PostBuffers(...)

        Placeholder method. With actual hardware this method will
        provide a list of the data buffers to the DAQ hardware.
        This is done by passing the numpy buffer array,
        from which the memory addresses to the underlying
        data elements are obtained by the DAQ wrapper.

        Parameters: boardhandle, python object containg the DAQ card
                                 memory handle

                    buffers, the numpy array containg all acqusition buffers

        Returns: True on success
        """

        return True

    def AcquireBuffers(self, boardHandle, buffers, bufIndex=0, bufPerAcq=1):
        """
        DummyHardware.AcquireBuffers(...)

        Write data to the specified buffers.
        Optionally write processed envelope data.

        Parameters: boardhandle, python object containg the DAQ card
                                 memory handle

                    buffers, ndarray containg all acqusition buffers.
                             Required array shape [bufferCnt, bufferLength]

                    bufIndex (int), the index of the first buffer to be written

                    bufPerAcq (int), the number of buffers to write before return

        Returns: True on success
        """
        a = bufIndex
        b = bufIndex + bufPerAcq

        sigAmp = 50
        sigRange = 2**16
        tempRF = numpy.random.randint(-sigAmp, sigAmp, (bufPerAcq,buffers.shape[1]) ) + 0.5*sigRange

        buffers[a:b,:] = numpy.array(tempRF, dtype=buffers.dtype)

        return True


    def IQDemodulateAvg(self, buffers, iqData, bufIndex, average=1, gain=None):
        """
        DummyHardware.IQDemodulateAvg(...)

        The core data processing algorithm. Responsible for producing envelope
        data from acquired buffers. Also responsible for applying averaging and
        post digitization time-gain amplification.

        IQDemodulateAvg() is critical to the overall performance of
        OpenHiFUS. As a result, it is recommended that processing is
        performed using an optimized python extension, coded and compiled
        using python's c language API. Using this approach it should also be
        straightforward to incorporate the CUDA or openCL for GPU processing
        using their native c API's.

        For the HardwareDummy class this method is essentially a placeholder
        as no actual processing is performed. Instead, a random array is
        generated for the idData argument.

        Parameters: boardhandle, python object containg the DAQ card
                                 memory handle

                    buffers, ndarray array containg all acqusition buffers.
                             Required array shape [bufferCnt, bufferLength]

                    iqData, ndarray that envelope data is written to.
                            Required array shape [1, bufferLength/decimation]

                    bufIndex (int), the index of the buffer to process

                    average (int), the number of buffers to average together.
                                   Included buffers will be: [bufIndex-average,
                                   bufIndex]

                    gain, ndarray of log scale gain values. required array shape
                          [1, bufferLength]

        Returns: True on success
        """
        envAmp = 10
        #Generate random data
        tempIQ = numpy.abs(numpy.random.rand(1,iqData.size))*envAmp
        #Simulate noise reduction from averaging
        tempIQ *= 1./average**0.5

        #Apply time gain if a gain curve is provided
        if gain is not None:
            n = self.recordCnt
            m = iqData.size / n
            tempIQ  = tempIQ.reshape([n,m])
            tempIQ += 20*numpy.log10(gain[0,::self.decimation])
            tempIQ  = tempIQ.reshape([1,iqData.size])

        iqData[:] = numpy.array(tempIQ, dtype=iqData.dtype)

        return True

    def StopAcquisition(self, boardHandle):
        """
        DummyHardware.StopAcquisition(...)

        Placeholder method. On actual hardware this will notify the DAQ
        to stop acquireing data.

        Parameters: boardhandle, python object containg the DAQ card
                                 memory handle

        Returns: True on success
        """

        return True

    def SetTriggerDelaySec(self, delay):
        """
        DummyHardware.SetTriggerDelay(...)

        Set the time belay between an acquisition trigger
        and the start of data recording.

        Parameters: delay (double), the delay time in seconds

        returns: True on success
        """

        self.triggerDelay = delay

        return True


def dataToBMode(data, imageData, imageDepth, imageLines):
    """ Function converts A scan lines into B mode image """

    srt = 0;
    for datasep in range(imageLines):
        imageData[:,datasep]=data[0,srt:srt+imageDepth];
        srt = srt+imageDepth;
    return True


def frequencySpectrum(xData,yData,timebase=1.0E+06):
    """
    Generate the frequency vector for the fft

    Keyword arguments:
        N - number of points in DFT(integer)
        df - frequency resolution (Hz)
    """

    #Make use of the fft capabilities in the numpy library
    #fft.fftfreq returns an array based on
    #f = [0, 1, ..., n/2-1, -n/2, ..., -1] / (d*n)         if n is even
    #f = [0, 1, ..., (n-1)/2, -(n-1)/2, ..., -1] / (d*n)   if n is odd

    N = len(xData)
    if N % 2 == 0:
        n = N/2 - 1
    else:
        n = (N-1) - 1
    w = numpy.fft.fftfreq(len(xData), xData[1]-xData[0]) / timebase
    H = numpy.fft.fft(yData) / N
    P = numpy.real(H*numpy.conjugate(H))

    return w[1:n], P[1:n]

class MCUWidget(QWidget):
    def __init__(self, parent=None):
        super(MCUWidget, self).__init__(parent)

        self.setWindowTitle("MCU")

        self.MCU = MCU()

        #Port Connection
        self.connectButton     = QPushButton("Connect to:")
        self.portIdEdit        = QLineEdit("Enter Port ID Here")
        if(self.MCU.autoConnect()):
            self.portIdEdit.setText(self.MCU.name)


        #Pulse amplitude (+)
        self.pulsePAmpButton = QPushButton("+ Pulse Amplitude: ")
        self.pulsePAmpSpinBox = QDoubleSpinBox()
        self.pulsePAmpSpinBox.setRange(0.00, 1.00)
        self.pulsePAmpSpinBox.setDecimals(2)
        self.pulsePAmpSpinBox.setSingleStep(0.05)
        self.pulsePAmpSpinBox.setValue(0.50)

        #Pulse amplitude (-)
        self.pulseNAmpButton = QPushButton("- Pulse Amplitude: ")
        self.pulseNAmpSpinBox = QDoubleSpinBox()
        self.pulseNAmpSpinBox.setRange(0.00, 1.00)
        self.pulseNAmpSpinBox.setDecimals(2)
        self.pulseNAmpSpinBox.setSingleStep(0.05)
        self.pulseNAmpSpinBox.setValue(0.50)

        #Bimorph scan (AC)
        self.ACButton = QPushButton("AC Scan")

        self.scanAmpSpinBox = QDoubleSpinBox()
        self.scanAmpSpinBox.setRange(0.00, 1.00)
        self.scanAmpSpinBox.setDecimals(2)
        self.scanAmpSpinBox.setSingleStep(0.05)
        self.scanAmpSpinBox.setValue(.20)

        self.scanFreqSpinBox = QDoubleSpinBox()
        self.scanFreqSpinBox.setRange(94.0, 97.0)
        self.scanFreqSpinBox.setDecimals(2)
        self.scanFreqSpinBox.setSingleStep(0.01)
        self.scanFreqSpinBox.setSuffix(" Hz")
        self.scanFreqSpinBox.setValue(95.75)
        #FPGA timer generation is at 400 MHz on 2**22 counter loop
        #400E+06 / 2** 22 = 95.37

        self.scanPhaseSpinBox = QDoubleSpinBox()
        self.scanPhaseSpinBox.setRange(0.0, 360.0)
        self.scanPhaseSpinBox.setDecimals(0)
        self.scanPhaseSpinBox.setSingleStep(1)
        self.scanPhaseSpinBox.setSuffix(" Deg")
        self.scanPhaseSpinBox.setValue(310.0)

        #Bimorph scan (DC)
        self.DCButton = QPushButton("DC Scan")

        self.scanDCSpinBox = QDoubleSpinBox()
        self.scanDCSpinBox.setRange(-1.0, 1.0)
        self.scanDCSpinBox.setDecimals(2)
        self.scanDCSpinBox.setSingleStep(.05)
        self.scanDCSpinBox.setValue(0.0)


        grid = QGridLayout()
        row = 0

        grid.addWidget(self.connectButton, row,0)
        grid.addWidget(self.portIdEdit, row,1)
        row += 1

        pulseSectionLabel = QLabel("Pulser Control")
        grid.addWidget(pulseSectionLabel, row, 0)
        row += 1

        grid.addWidget(self.pulsePAmpButton, row,0)
        grid.addWidget(self.pulsePAmpSpinBox, row, 1)
        row += 1

        grid.addWidget(self.pulseNAmpButton, row,0)
        grid.addWidget(self.pulseNAmpSpinBox, row, 1)
        row += 1

        scanSectionLabel = QLabel("Scanner Control")
        grid.addWidget(scanSectionLabel, row, 0)
        row += 1

        grid.addWidget(self.ACButton, row,0)
        row += 1

        scanAmpLabel = QLabel("Scanner Amplitude: ")
        grid.addWidget(scanAmpLabel, row,0)
        grid.addWidget(self.scanAmpSpinBox, row,1)
        row += 1

        scanFreqLabel = QLabel("Scanner Frequency: ")
        grid.addWidget(scanFreqLabel, row,0)
        grid.addWidget(self.scanFreqSpinBox, row, 1)
        row += 1

        scanPhaseLabel = QLabel("Scanner Phase: ")
        grid.addWidget(scanPhaseLabel, row,0)
        grid.addWidget(self.scanPhaseSpinBox, row, 1)
        row +=1

        grid.addWidget(self.DCButton, row,0)
        row += 1

        scanDCLabel = QLabel("DC output: ")
        grid.addWidget(scanDCLabel, row,0)
        grid.addWidget(self.scanDCSpinBox, row, 1)
        row += 1

        VBox = QVBoxLayout()
        VBox.addLayout(grid)
        VBox.addStretch()

        self.setLayout(VBox)

        self.connect(self.connectButton, SIGNAL("clicked()"), self.connectMCU)
        self.connect(self.pulsePAmpButton, SIGNAL("clicked()"), self.setPPulse)
        self.connect(self.pulsePAmpSpinBox, SIGNAL("valueChanged(double)"), self.setPPulse)
        self.connect(self.pulseNAmpButton, SIGNAL("clicked()"), self.setNPulse)
        self.connect(self.pulseNAmpSpinBox, SIGNAL("valueChanged(double)"), self.setNPulse)
        self.connect(self.ACButton, SIGNAL("clicked()"), self.setAC)
        self.connect(self.scanAmpSpinBox,  SIGNAL("valueChanged(double)"), self.setAmplitude)
        self.connect(self.scanFreqSpinBox,  SIGNAL("valueChanged(double)"), self.setFrequency)
        self.connect(self.scanPhaseSpinBox, SIGNAL("valueChanged(double)"), self.setPhase)
        self.connect(self.DCButton, SIGNAL("clicked()"), self.setDC)
        self.connect(self.scanDCSpinBox, SIGNAL("valueChanged(double)"), self.setDC)


    def connectMCU(self):
        portIDtext = unicode(self.portIdEdit.text())
        self.MCU.connect(portIDtext)

    def setAC(self):
        self.MCU.setAC()

    def setAmplitude(self):
        val = self.scanAmpSpinBox.value()
        self.MCU.setAmplitude(val)

    def setFrequency(self):
        val = self.scanFreqSpinBox.value()
        self.MCU.setFrequency(val)

    def setPhase(self):
        val = self.scanPhaseSpinBox.value()
        self.MCU.setPhase(val)

    def setPPulse(self):
        val = self.pulsePAmpSpinBox.value()
        self.MCU.setPPulse(val)

    def setNPulse(self):
        val = self.pulseNAmpSpinBox.value()
        self.MCU.setNPulse(val)

    def setDC(self):
        val = self.scanDCSpinBox.value()
        self.MCU.setDC(val)



class MCU(serial.Serial):
    """ Class definition for serial communication to Arduino
        w/ added functionality specific to the MCU

        Notes:
        1 - MCU is inherited form serial.Serial
        2 - Initialization does not open the serial connection
        3 - Do not directly call the inherited open() method, as
            the Arduino requires reboot time, the connect() method
            allows for this.
        """

    opCode = {
        'AC':            0, \
        'AMP_ADJUST':    1, \
        'FREQ_ADJUST':   2, \
        'PHASE_ADJUST':  3, \
        'DC':            4, \
        'PPULSE_ADJUST': 5, \
        'NPULSE_ADJUST': 6, \
        'ECHO':          7  \
        }

    fmtCode = {
        'ubyte':    'B', \
        'ushort':   'H', \
        'float':    'f'  \
        }

    def __init__(self):
        """Intialize the serial class but do not open connection"""
        serial.Serial.__init__(self, port=None, baudrate=9600, timeout=1.0, writeTimeout=1.0)


    def listPorts(self):

        port_list = []
        #Quickly scan all possible COM port adresses
        import serial
        for i in range(256):
            try:
                sTest = serial.Serial(i)
                port_list.append(sTest.portstr)
                port = i
                sTest.close()
            except serial.SerialException:
                pass

        return port_list


    def connect(self, portID):
        """Connect to the specified port and pause for Arduino reboot"""
        self.port = portID
        try:
            #ensure the specified port is close to begin with
            self.close()
            self.open()
            #wait for device to reboot
            time.sleep(2.0)
            #Test connection
            if(bool(self.sendEcho(True))):
                return True
            else:
                self.close()
                return False

        except serial.SerialException:
            self.close()
            self.port = ''
            return False


    def autoConnect(self):

        port_list = self.listPorts()
        autoResult = False

        for port in port_list:
            if self.connect(port) ==  True:
                autoResult = True
                break
            else:
                autoResult = False

        #end port_list

        return autoResult


    def _send(self, cmd, data, fmt):
        """Private function used to send serial data"""

        try:
            cmdString      = struct.pack(self.fmtCode['ubyte'], cmd)
            self.write(cmdString)

            dataString     = struct.pack(fmt, data)
            self.write(dataString)
            return True

        except:
            return False


    def setAC(self):
        """ Resume AC scan signal """
        self._send(self.opCode['AC'], 0, self.fmtCode['ushort'])

    def setAmplitude(self, k):
        """ Set the scanner amplitude [0, 1] """
        if k >= 0.0 and k <= 1.0:
            self._send(self.opCode['AMP_ADJUST'], k, self.fmtCode['float'])

    def setFrequency(self, f):
        """ Set the scanner frequency, f = [10, 1000] """
        if f >= 10.0 and f <= 1000.0:
            self._send(self.opCode['FREQ_ADJUST'], f, self.fmtCode['float'])

    def setPhase(self, phi):
        if phi >= 0 and phi <= 360:
            self._send(self.opCode['PHASE_ADJUST'], phi, self.fmtCode['ushort'])

    def setDC(self, DCval):
        if DCval >= -1.0 and DCval <= 1.0:
            self._send(self.opCode['DC'], DCval, self.fmtCode['float'])

    def setPPulse(self, k):
        if k >= 0.0 and k <= 1.0:
            self._send(self.opCode['PPULSE_ADJUST'], k, self.fmtCode['float'])

    def setNPulse(self, k):
        if k >= 0.0 and k <= 1.0:
            self._send(self.opCode['NPULSE_ADJUST'], k, self.fmtCode['float'])

    def sendEcho(self, echoCode):
        self._send(self.opCode['ECHO'], echoCode, self.fmtCode['ushort'])
        return self.readline()

try:
    import PyDaxAlazar as DAQ
except:
    DAQ = DummyHardware()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    #splash_pix = QPixmap('')
    #splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
    #splash.show()
    form = MainWindow()
    form.setWindowState(Qt.WindowMaximized)
    form.show()
    #splash.finish(form)
    app.exec_()
