OpenHiFUS
=========
Real-time data acquisition and image processing for high frequency ultrasound

Copyright 2012-2013 Jeff Leadbetter
jeff.leadbetter@dal.ca

OpenHiFUS demonstrates a real-time data acquisition and processing approach using 
the Python language. This software is made available in hope that it will be a 
useful example to other researchers in the ultrasound and medical imaging community, 
or others who are interested in scientific or engineering applications requiring 
high speed data acquisition and display. It is the author's opinion that the Python 
language, with its wide variety of freely available packages and libraries, is an 
extremely powerful and valuable tool to the scientific community. However, when 
starting this project it was found that there were few comprehensive examples for 
using Python to run a real-time data acquisition and display system.  Now, OpenHiFUS 
demonstrates a simple approach for running multiple Python processes to accommodate 
uninterrupted data acquisition, and independent processing and display rates.

As distributed, OpenHiFUS will generate random data or load existing data to 
demonstrate performance and functionality. Additionally, OpenHiFUS can load 
external drivers in order to function with many types of digital acquisition 
hardware. Note that using external drivers will also typically require a 
wrapper module to interface with the generalized form of OpenHiFUS. By following 
the template provided within the source code it is hoped that the process of utilizing 
external drivers and preparing wrapper modules is a reasonably straight forward process.

INSTALLATION

OpenHiFUS is a single file application. The fastest way to be up and running is to 
install a PythonXY package (https://code.google.com/p/pythonxy/) based on Python 2.7. 
Not included in the PythonXY package is the OpenCV library, which is also required 
and can be obtained from http://opencv.willowgarage.com/wiki/.

If a python PythonXY package is not installed, the following is a list of libraries 
required in addition to a Python 2.7 distribution:

NumPy (http://www.numpy.org/)
PyQt4 (http://www.riverbankcomputing.com/software/pyqt/intro)
PyQwt (http://pyqwt.sourceforge.net/)
Guiqwt (https://code.google.com/p/guiqwt/)
OpenCV (http://opencv.willowgarage.com/wiki/) 
