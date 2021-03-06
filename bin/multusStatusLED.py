#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Karl Keusgen
#
# 2017-04-12
#
# Nutzung des DO2 als Indikator für Verbindungen
# 
# 0 DO2 Aus:			Prozess läuft nicht oder interner Fehler
# 1 DO2 Blinkt Schnell:	Keine Internet/keien VPn verbindunmg
# 2 DO2 Blinkt langsam:	Internet verbindung keine VPN verbindung
# 3 DO2 An:				Internet verbindung und VPN Verbindung OK
#
##
## 2018-11-12 
## Alles nochmal überarbeitet.. ordentlich gedeaemonized
#
#
# 2019-11-04
# Transformed into a class and fitted it into multus III cocept
#
# 2019-11-28
# changed it from thrift and file stuff to a gRPC Protobuf application
# with direct hardware access
#

import sys
import time
import os
import signal
from daemonize import Daemonize

sys.path.append('/multus/lib')
import libpidfile
import multusdConfig
import multusdTools
import multusdModuleConfig
import NetworkStatus

import libmultusStatusLED

## do the Periodic Alive Stuff
import multusdControlSocketClient

# 2020-06-01
# Json config option
if libmultusStatusLED.UseJsonConfig:
	import libmultusdJson
	import libmultusdJsonModuleConfig

class StatusLEDClass(object):

	def __init__(self):

		self.StatusLEDIsRunningTwice = False
		self.ObjmultusdTools = multusdTools.multusdToolsClass()

		## 2020-06-01
		if libmultusStatusLED.UseJsonConfig:
			# first we get the config of the multusd system
			self.ObjmultusdConfig = libmultusdJson.multusdJsonConfigClass(ObjmultusdTools = self.ObjmultusdTools)
			bSuccess = self.ObjmultusdConfig.ReadConfig()
			if bSuccess:
				ObjmultusdModulesConfig = libmultusdJsonModuleConfig.ClassJsonModuleConfig(self.ObjmultusdConfig, None)
				bSuccess = ObjmultusdModulesConfig.ReadJsonModulesConfig()
			if not bSuccess:
				print ("Something went wrong while reading in the modules.. we leave")
				sys.exit(1)
		else:
			# first we get the config of the multusd system
			ObjmultusdConfig = multusdConfig.ConfigDataClass()
			ObjmultusdConfig.readConfig()
			
			## after we got the modules init file.. we have to read it, to get the config files for this process
			ObjmultusdModulesConfig = multusdModuleConfig.ClassModuleConfig(ObjmultusdConfig)
			ObjmultusdModulesConfig.ReadModulesConfig()

		self.ModuleControlPort = 43000
		self.ModuleControlPortEnabled = True

		#WalkThe list of modules to find our configuration files.. 
		Ident = "multusStatusLED"
		for Module in ObjmultusdModulesConfig.AllModules:
			if Module.ModuleParameter.ModuleIdentifier == Ident:
				if libmultusStatusLED.UseJsonConfig:
					self.ObjmultusStatusLEDConfig = libmultusStatusLED.StatusLEDConfigClass(None)
					bSuccess = self.ObjmultusStatusLEDConfig.ReadJsonConfig(self.ObjmultusdTools, self.ObjmultusdConfig, Ident)
					if not bSuccess:
						print ("Error getting Json config, we exit")
						sys.exit(2)
				else:
					self.ObjmultusStatusLEDConfig = libmultusStatusLED.StatusLEDConfigClass(Module.ModuleParameter.ModuleConfig)
					self.ObjmultusStatusLEDConfig.ReadConfig()
					self.ModuleControlPortEnabled = Module.ModuleParameter.ModuleControlPortEnabled 

				self.LPIDFile = Module.ModuleParameter.ModulePIDFile
				self.ModuleControlPort = Module.ModuleParameter.ModuleControlPort 
				break

		self.LogFile = ObjmultusdConfig.LoggingDir +"/" + Module.ModuleParameter.ModuleIdentifier + ".log"
		if self.LogFile:
			## We initialize logging
			self.ObjmultusdTools.InitGlobalLogging(self.LogFile)
		else:
			self.ObjmultusdTools.InitGlobalLogging("/dev/null")
	
		# Signal handler initialisieren
		signal.signal(signal.SIGTERM, self.__handler__)
		signal.signal(signal.SIGINT, self.__handler__)

		## Do the PIDFIle
		try:
			self.StatusLEDIsRunningTwice = False
			print ("We Try to do the PIDFile: " + self.LPIDFile)
			with(libpidfile.PIDFile(self.LPIDFile)):
				print ("Writing PID File: " + self.LPIDFile)
		except:
			ErrorString = self.ObjmultusdTools.FormatException()
			self.ObjmultusdTools.logger.debug("Error: " + ErrorString)
			self.StatusLEDIsRunningTwice = True
			sys.exit(1)

		## get the hardware access
		self.ObjmultusStatusLEDFunctions = libmultusStatusLED.StatusLEDFunctionsClass(self.ObjmultusStatusLEDConfig, self.ObjmultusdTools)
		self.ObjLANWANStatus = NetworkStatus.gRPCLANWANStatusClass(self.ObjmultusdTools)
		self.ObjOVPNStatus = NetworkStatus.gRPCOVPNStatusClass(self.ObjmultusdTools)

		self.KeepItRunning = True

		return

	def __del__(self):
		self.ObjmultusStatusLEDFunctions.LEDOff()

		try:
			if not self.StatusLEDIsRunningTwice:
				os.remove(self.LPIDFile)
		except:
			ErrorString = self.ObjmultusdTools .FormatException()
			self.ObjmultusdTools.logger.debug("Error: " + ErrorString)

		return


	# Receiving the kill signal, ensure that the heating is off
	def __handler__(self, signum, frame):
		timestr = time.strftime("%Y-%m-%d %H:%M:%S") + " | "

		print (timestr + 'Signal handler called with signal ' + str(signum))
		
		if signum == 15 or signum == 2:
			self.KeepItRunning = False

		sys.exit(0)

		return


	def haupt (self, bDaemon):

		## setup the periodic alive mnessage stuff
		if self.ModuleControlPortEnabled and bDaemon:
			self.ObjmultusdTools.logger.debug("Setup the periodic Alive messages")
			self.periodic = multusdControlSocketClient.ClassControlSocketClient(self.ObjmultusdTools, 'localhost', self.ModuleControlPort)
			self.periodic.ConnectFeedbackSocket()
		else:
			self.ObjmultusdTools.logger.debug("Alive Message to multusd FeedBack port are not enabled")

		LEDStatus = False
		ConnectionStatus = 0
		Counter = 0
		RefreshCounter = 0
		iErrors = -1
		vErrors = -1
		 
		while (self.KeepItRunning):
			
			#self.ObjmultusdTools.logger.debug("Run in Loop")
			
			## DO the peridoc call against the multusd
			if self.ModuleControlPortEnabled and bDaemon:
				self.periodic.SendPeriodicMessage()

			#read Errors Internet connection
			if self.ObjmultusStatusLEDConfig.LEDInternetEnable:
				LocalLANWANStatus, ConnectionStatus = self.ObjLANWANStatus.GetWANStatus("StatusLED WAN Status Request")
				if not LocalLANWANStatus.ValidStatus:
					iErrors = -1
				elif not LocalLANWANStatus.ConnectionStatus:
					iErrors = 1
				elif LocalLANWANStatus.ConnectionStatus:
					iErrors = 0

			if self.ObjmultusStatusLEDConfig.LEDVPNEnable:
				LocalOVPNStatus, ConnectionStatus = self.ObjOVPNStatus.GetOVPNStatus("StatusLED OVPN Status Request")
				if not LocalOVPNStatus.ValidStatus:
					vErrors = -1
				elif not LocalOVPNStatus.ConnectionStatus:
					vErrors = 1
				elif LocalOVPNStatus.ConnectionStatus:
					vErrors = 0

			print ("InternetErrors: " + str(iErrors))
			print ("OpenVPNErrors:  " + str(vErrors))

			if iErrors < 0:
				ConnectionStatus = 0
			elif iErrors == 0 and vErrors == 0:
				ConnectionStatus = 3
			elif iErrors == 0 and vErrors != 0:
				ConnectionStatus = 2
			elif iErrors > 0:	
				ConnectionStatus = 1

			if ConnectionStatus == 0:
				Counter = 0
				LEDStatus = self.ObjmultusStatusLEDFunctions.LEDOff()

			elif ConnectionStatus == 1:
				if LEDStatus:
					Counter = 0
					LEDStatus = self.ObjmultusStatusLEDFunctions.LEDOff()
				else:
					Counter = 0
					LEDStatus = self.ObjmultusStatusLEDFunctions.LEDOn()

			elif ConnectionStatus == 2:

				if LEDStatus and Counter >= 3:
					Counter = 0
					LEDStatus = self.ObjmultusStatusLEDFunctions.LEDOff()
				elif not LEDStatus and Counter >= 3:
					Counter = 0
					LEDStatus = self.ObjmultusStatusLEDFunctions.LEDOn()

			elif ConnectionStatus == 3:
				Counter = 0
				if not LEDStatus or RefreshCounter >= 120:
					RefreshCounter = 0	
					LEDStatus = self.ObjmultusStatusLEDFunctions.LEDOn()

		
			## Damit ab und zu das LED-Signal aktualisiert wird
			## Der thrift-Prozess koennte ja neu gestartet sein
			RefreshCounter += 1

			Counter += 1
			time.sleep (1.0)

def DoTheDeamonJob(bDaemon = True):

	ObjmultusStatusLED = StatusLEDClass()  
	ObjmultusStatusLED.haupt(bDaemon)

	return

if __name__ == "__main__":

	# Check program must be run as daemon or interactive
	# ( command line parameter -n means interactive )
	bDeamonize = True
	for eachArg in sys.argv:   
		if str(eachArg) == '-n' :
			bDeamonize = False
	 
	if bDeamonize:
		print ("Starten im deamonize modus")

		pid = "/tmp/dummy.pid"
		
		# Daemonize this job
		myname=os.path.basename(sys.argv[0])
		daemon = Daemonize(app=myname, pid=pid, action=DoTheDeamonJob)
		daemon.start()
		
	else:
		print ("Starten im consolen modus")
		DoTheDeamonJob (False)
