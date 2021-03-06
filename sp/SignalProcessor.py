# Intan/Opal Kelly Python Interface Module
# By Stuart Maitland

# Provides an interface to the Intan RHD2000 board
# Extends the compiled/ automatically generated xem module provided by Opal Kelly, built in C++


import ok
import numpy
from SignalResponse import SignalResponse
import os

example_settings = {
    'continuous_capture': False,
    'sample_rate': '30000',
    'num_data_streams': 2,
    'num_channels': 64,
    'cable_delay': {'PortA': 5},
    'capture_duration': 100
}


class DESTester:
    def __init__(self, settings=example_settings):
        self.xem = ok.okCFrontPanel()
        self.initializeDevice()
        self.init_experiment(settings)
        self.num_channels = settings['num_channels']
        self.capture_duration = settings['capture_duration']

    def initializeDevice(self):
        # Open the first device we find.
        if self.xem.NoError != self.xem.OpenBySerial(""):
            raise RuntimeError("A device could not be opened.  Is one connected, or in use by another process?")

        # Get some general information about the device.
        self.devInfo = ok.okTDeviceInfo()

        if self.xem.NoError != self.xem.GetDeviceInfo(self.devInfo):
            print("Unable to retrieve device information.")
            return False
        print("         Product: " + self.devInfo.productName)
        print("Firmware version: %d.%d" % (self.devInfo.deviceMajorVersion, self.devInfo.deviceMinorVersion))
        print("   Serial Number: %s" % self.devInfo.serialNumber)
        print("       Device ID: %s" % self.devInfo.deviceID)

        self.xem.LoadDefaultPLLConfiguration()

        # Download the configuration file.
        if self.xem.NoError != self.xem.ConfigureFPGA("main.bit"):
            print("FPGA configuration failed.")
            return False

        # Check for FrontPanel support in the FPGA configuration.
        if not self.xem.IsFrontPanelEnabled():
            print("FrontPanel support is not available.")
            return False

        print("FrontPanel support is available.")

        self.resetBuffer()
        return True

    def init_experiment(self, settings):
        for i in range(settings['num_data_streams'] + 1):
            self.enableDataStream(i)
            self.setDataSource(i, i)
        self.setContinuousRunMode(settings['continuous_capture'])
        self.setSampleFrequency(settings['sample_rate'])
        self.setCableDelay(settings['cable_delay'])

    def setKey(self, key):
        for i in range(4):
            self.xem.SetWireInValue((0x0b - i), key[i], 0xffff)
        self.xem.UpdateWireIns()

    def resetBuffer(self):
        """
        Resets the USB buffer on the OK board
        """
        self.xem.SetWireInValue(0x10, 0xff, 0x01)
        self.xem.UpdateWireIns()
        self.xem.SetWireInValue(0x10, 0x00, 0x01)
        self.xem.UpdateWireIns()
        self.LightPulse([255, 0, 255])

    def resetBoard(self):
        """
        Resets the FPGA- clears all auxiliary command RAM banks, clears USB FIFO, resets sampling rate to 30Ks/S
        :return:
        """
        self.xem.SetWireInValue(0x00, 0x01, 0x01)
        self.xem.UpdateWireIns()
        self.xem.SetWireInValue(0x00, 0x00, 0x01)
        self.xem.UpdateWireIns()

    def encryptDecrypt(self, infile, outfile):
        file_in = open(infile, "rb")
        file_out = open(outfile, "wb")

        # Reset the RAM address pointer.
        self.xem.ActivateTriggerIn(0x41, 0)

        while file_in:
            buf = bytearray(file_in.read(2048))

            got = len(buf)
            if (got == 0):
                break

            if (got < 2048):
                buf += b"\x00" * (2048 - got)

            # Write a block of data.
            self.xem.ActivateTriggerIn(0x41, 0)
            self.xem.WriteToPipeIn(0x80, buf)

            # Perform DES on the block.
            self.xem.ActivateTriggerIn(0x40, 0)

            # Wait for the TriggerOut indicating DONE.
            for i in range(100):
                self.xem.UpdateTriggerOuts()
                if self.xem.IsTriggered(0x60, 1):
                    break

            self.xem.ReadFromPipeOut(0xa0, buf)
            file_out.write(buf)

        file_in.close()
        file_out.close()

    def encrypt(self, infile, outfile):
        print("Encrypting %s ----> %s" % (infile, outfile))
        # Set the encrypt Wire In.
        self.xem.SetWireInValue(0x0010, 0x0000, 0x0010)
        self.xem.UpdateWireIns()
        self.encryptDecrypt(infile, outfile)

    def decrypt(self, infile, outfile):
        print("Decrypting %s ---> %s" % (infile, outfile))
        # Set the decrypt Wire In.
        self.xem.SetWireInValue(0x0010, 0x00ff, 0x0010)
        self.xem.UpdateWireIns()
        self.encryptDecrypt(infile, outfile)

    def setLight(self, i):
        """
        Cascades red LEDs on OK machine
        :param i: 0:255 int/binary, represents the binary 8 LED state
        :return: None
        """
        self.xem.SetWireInValue(0x11, i)
        self.xem.UpdateWireIns()

    def LightPulse(self, arr, interval=1):
        if type(arr) == int:
            self.setLight(arr)
            # time.sleep(0.1)
        else:
            for i in arr:
                self.setLight(i)
                i += interval
                # time.sleep(0.1)
        self.setLight(0)

    def startRecording(self):
        # Initiate SPI dad acquisition
        self.xem.ActivateTriggerIn(0x41, 0)

    def isRunning(self):
        # Checks whether the board is currently evaluating a data block
        self.xem.UpdateWireOuts()
        return self.xem.GetWireOutValue(0x22)

    def setContinuousRunMode(self, continuousMode):
        # Set the continuous recording mode i.e. run whether the computer is ready for data or not
        if continuousMode:
            self.xem.SetWireInValue(0x00, 0x02, 0x02)
        else:
            self.xem.SetWireInValue(0x00, 0x00, 0x02)
        self.xem.UpdateWireIns()

    def numWordsInFifo(self):
        self.xem.UpdateWireOuts()
        msb = self.xem.GetWireOutValue(0x21)
        lsb = self.xem.GetWireOutValue(0x20)
        return (msb << 16 + lsb)

    def setMaxTimeStep(self, maxTimeStep):
        # Set the amount of time the board should listen for data over

        # I have no idea why you need to do this least/most sig bit but its in the source so
        maxTimeStepLsb = maxTimeStep & 0x0000ffff
        maxTimeStepMsb = maxTimeStep & 0xffff0000

        # These are just the magic addresses for switching on the timers
        self.xem.SetWireInValue(0x01, maxTimeStepLsb)
        self.xem.SetWireInValue(0x02, maxTimeStepMsb >> 16)
        self.xem.UpdateWireIns()

    def collectDataFromPipeOut(self, length, numStreams):
        # Starts the timer, waits until an amount of data is available on the USB buffer, then collects it
        self.setMaxTimeStep(length)
        buffer = bytearray("\x00" * self.dataBlockSize(numStreams) * length)
        self.setLight(255)
        self.startRecording()
        while self.isRunning():
            pass
        # Read from the Data pipe out- note that buffer passed is overwritten with the new data source in doing this.
        self.xem.ReadFromPipeOut(0xa0, buffer)
        self.setLight(0)
        return buffer

    def enableDataStream(self, streamIndex):
        # Enables or disables streams
        self.xem.SetWireInValue(0x14, 0x0001 << streamIndex, 0x0001 << streamIndex)
        self.xem.UpdateWireIns()

    def setDataSource(self, stream, boardDataSource):
        # Links a data source (port A1,A2,B1,B2...D2) to one of 8 available USB data streams
        # Data source is 0:A1,1:A2,2:B1,3:B2,...,7:D2

        # if the datastream is higher than 4 we select a different wire in for it
        high_four = (stream * 4) // 16
        bitshift = (stream * 4) - (high_four * 16)
        wire_in = 0x12 + high_four

        self.xem.SetWireInValue(wire_in, boardDataSource << bitshift, 0x000f << bitshift)
        self.xem.UpdateWireIns()

    def dataBlockSize(self, numDataStreams):
        """
        Calculates the expected size in bytes of a single sample of data
        Note this differs from the Intan example as it returns bytes rather than 16 bit words (because thats stupid)
        :param numDataStreams: number of data streams
        :return: int
        """
        # 4 = magic number; 2 = time stamp; 36 = (32 amp channels + 3 aux commands + 1 filler word); 8 = ADCs; 2 = TTL in/out
        return (2 * (4 + 2 + numDataStreams * 36 + 8 + 2))

    @staticmethod
    def bytesToVolts(bytes):
        """
        :param bytes: int/array of RHD2000 amplifier waveforms
        :return: int/array microvolts
        """
        return 0.195 * bytes

    def setSampleFrequency(self, rate):
        """
        # Assuming a 100 MHz reference clock is provided to the FPGA, the programmable FPGA clock frequency
        # is given by:
        #
        #       FPGA internal clock frequency = 100 MHz * (M/D) / 2
        #
        # M and D are "multiply" and "divide" integers used in the FPGA's digital clock manager (DCM) phase-
        # locked loop (PLL) frequency synthesizer, and are subject to the following restrictions:
        #
        #                M must have a value in the range of 2 - 256
        #                D must have a value in the range of 1 - 256
        #                M/D must fall in the range of 0.05 - 3.33
        #
        # (See pages 85-86 of Xilinx document UG382 "Spartan-6 FPGA Clocking Resources" for more details.)
        #
        # This variable-frequency clock drives the state machine that controls all SPI communication
        # with the RHD2000 chips.  A complete SPI cycle (consisting of one CS pulse and 16 SCLK pulses)
        # takes 80 clock cycles.  The SCLK period is 4 clock cycles; the CS pulse is high for 14 clock
        # cycles between commands.
        #
        # Rhythm samples all 32 channels and then executes 3 "auxiliary" commands that can be used to read
        # and write from other registers on the chip, or to sample from the temperature sensor or auxiliary ADC
        # inputs, for example.  Therefore, a complete cycle that samples from each amplifier channel takes
        # 80 * (32 + 3) = 80 * 35 = 2800 clock cycles.
        #
        # So the per-channel sampling rate of each amplifier is 2800 times slower than the clock frequency.
        #
        # Based on these design choices, we can use the following values of M and D to generate the following
        # useful amplifier sampling rates for electrophsyiological applications:
        #
        #   M    D     clkout frequency    per-channel sample rate     per-channel sample period
        #  ---  ---    ----------------    -----------------------     -------------------------
        #    7  125          2.80 MHz               1.00 kS/s                 1000.0 usec = 1.0 msec
        #    7  100          3.50 MHz               1.25 kS/s                  800.0 usec
        #   21  250          4.20 MHz               1.50 kS/s                  666.7 usec
        #   14  125          5.60 MHz               2.00 kS/s                  500.0 usec
        #   35  250          7.00 MHz               2.50 kS/s                  400.0 usec
        #   21  125          8.40 MHz               3.00 kS/s                  333.3 usec
        #   14   75          9.33 MHz               3.33 kS/s                  300.0 usec
        #   28  125         11.20 MHz               4.00 kS/s                  250.0 usec
        #    7   25         14.00 MHz               5.00 kS/s                  200.0 usec
        #    7   20         17.50 MHz               6.25 kS/s                  160.0 usec
        #  112  250         22.40 MHz               8.00 kS/s                  125.0 usec
        #   14   25         28.00 MHz              10.00 kS/s                  100.0 usec
        #    7   10         35.00 MHz              12.50 kS/s                   80.0 usec
        #   21   25         42.00 MHz              15.00 kS/s                   66.7 usec
        #   28   25         56.00 MHz              20.00 kS/s                   50.0 usec
        #   35   25         70.00 MHz              25.00 kS/s                   40.0 usec
        #   42   25         84.00 MHz              30.00 kS/s                   33.3 usec
        #
        # To set a new clock frequency, assert new values for M and D (e.g., using okWireIn modules) and
        # pulse DCM_prog_trigger high (e.g., using an okTriggerIn module).  If this module is reset, it
        # reverts to a per-channel sampling rate of 30.0 kS/s.
        """
        sampleFrequencies = {
            '1000': [7, 125],
            '1250': [7, 100],
            '1500': [21, 250],
            '2000': [14, 125],
            '2500': [25, 250],
            '3000': [21, 125],
            '3330': [14, 75],
            '4000': [28, 125],
            '5000': [7, 25],
            '6250': [7, 20],
            '8000': [112, 250],
            '10000': [14, 25],
            '12500': [7, 10],
            '15000': [21, 25],
            '20000': [28, 25],
            '25000': [35, 25],
            '30000': [42, 25]
        }

        self.xem.SetWireInValue(0x03, (256 * sampleFrequencies[rate][0] + sampleFrequencies[rate][1]))
        self.xem.UpdateWireIns()
        self.xem.ActivateTriggerIn(0x40, 0)

    def setCableDelay(self, delaydict):
        """
        Sets the delay for sampling the MISO line on SPI ports in integer clock steps (1/2800 of a per-channel
        sampling period.
        Note: Set cable delay after sample rate is changed
        :param delaydict: PortABCD of connected SPI port: cable delay in integer clock steps (0:15)
        :return:
        """
        for item in delaydict.items():
            # Transforms to tuple- get ports from this
            port = item[0]
            delay = item[1]
            # Delay must be between 0 and 15
            delay = max(min(15, delay), 0)
            shift = {
                "PortA": 0,
                "PortB": 4,
                "PortC": 8,
                "PortD": 12
            }
            self.xem.SetWireInValue(0x04, delay << shift[port], 0x000f << shift[port])
            self.xem.UpdateWireIns()

    def checkHeader(self, header):
        # Confirms the first 64 bits of the USB header against the Rhythm magic number to verify sync

        # OK, there's a lot going on on this line.
        # Unpack the byte array, coerced into a bytes object
        # < means little endian, Q indicates unsigned long long
        # By default returns a signed tuple, so just get the first element.
        # Reference: https://docs.python.org/3/library/struct.html
        parsedHeader = numpy.frombuffer(bytes(header), numpy.dtype("<Q"))
        return (parsedHeader == 0xc691199927021942)

    def readDataBlock(self, buffer, samplesPerDataBlock, numDataStreams):
        """
        Takes raw data from the USB buffer on the board and converts it into something usable.
        :param buffer: byte array object, the size of what you want to get
        :param samplesPerDataBlock: number of samples expected
        :param numDataStreams: int number of data streams
        :return:
        """
        # First we initialise some local variables
        num_channels = self.num_channels
        index = 0
        time_stamp = []
        auxiliary_data = numpy.zeros((100, 100, 100,))
        total_unsorted = []
        amplifier_data = numpy.zeros((numDataStreams, num_channels, samplesPerDataBlock))
        board_adc_data = numpy.zeros((100, 100))
        ttl_in = []
        ttl_out = []

        #   The data is arranged in the following format on the board:
        #       8 byte header
        #       4 byte timestamp
        #       n byte auxiliary data
        #       n byte amplifier data (the one we want)
        #       n byte filler word
        #       128 byte ADC5662 data
        #       4 byte ttlIn + ttOut data

        for sample in xrange(0, samplesPerDataBlock):

            # Check the first 8 bytes to match the RHD2000 magic header word
            if not self.checkHeader(buffer[index:index + 8]):
                print("")
                raise SyntaxError("Error in readDataBlock: Incorrect header: {0}".format(buffer[index:index + 8]))
            index += 8

            # Read the timestamp
            # This time it's L- unsigned long
            time_stamp.append(numpy.frombuffer(buffer[index:index + 2], numpy.dtype("<L")))
            index += 4

            # Read auxiliary input
            for channel in xrange(0, 3):
                for stream in xrange(0, numDataStreams):
                    # The rest are H, unsigned short
                    auxiliary_data[stream][channel][sample] = numpy.frombuffer(buffer[index:index + 2], numpy.dtype("<H"))
                    index += 2

            # Read amplifier channels- this is the one we really want
            numpifiedData = numpy.frombuffer(buffer[index:index + (2 * num_channels * numDataStreams)],
                                             numpy.dtype("<H"))
            numpifiedData = numpy.reshape(numpifiedData, (-1, 2)).T
            for channel in xrange(0, num_channels):
                for stream in xrange(0, numDataStreams):
                    amplifier_data[stream][channel][sample] = numpifiedData[stream][channel]
                    # amplifierData[stream][channel][sample] = unpack("<H", buffer[index:index + 2])[0]
            index += 2 * num_channels * numDataStreams
            # Skip 36th filler word in each data stream

            index += 2 * numDataStreams

            # Read from AD5662 ADCs
            for i in xrange(0, 8):
                board_adc_data[i][sample] = numpy.frombuffer(buffer[index:index + 2], numpy.dtype("<H"))
                index += 2

            # Read TTL input and output values

            ttl_in.append(numpy.frombuffer(buffer[index:index + 2], numpy.dtype("<H")))
            index += 2
            ttl_out.append(numpy.frombuffer(buffer[index:index + 2], numpy.dtype("<H")))
            index += 2

            # Construct signal response object
        return SignalResponse(time_stamp, auxiliary_data, amplifier_data, board_adc_data, ttl_in, ttl_out, total_unsorted)
