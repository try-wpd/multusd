# -*- coding: utf-8 -*-
#
# Karl Keusgen
#
# 2019-11-24
# the first gRPC protobuf based application of mine
#
# 2019-12-06
# redone

import sys
import time
import subprocess
import os
import configparser

sys.path.append('/multus/lib')
import libmultusLANWANCheck
"""
import libmultusdBNKStatus
"""
import multusdBasicConfigfileStuff

## now the protobuf stuff
import grpc
sys.path.append('/multus/lib/proto')
import LANWANOVPNCheck_pb2
import LANWANOVPNCheck_pb2_grpc
from concurrent import futures

# 2020-06-01
# Json config option
import libUseJsonConfig
UseJsonConfig = libUseJsonConfig.UseJsonConfig
#UseJsonConfig = True
import urllib.request
import json

############################################################################################################
#
# 2019-12-07
# Class to be called by multusdService
# it is mandatory for each native multusd process, who uses the controlPort function
# to have a class like this
#
class FailSafeClass(object):
	def __init__(self, Tools, ModuleConfig, Ident, dBNKEnabled):
		
		self.Ident = Ident

				## We get the gRPC stuff for doing refresh on dBNK, if enabled
		self.ObjdBNKStatus = None

		"""
		if dBNKEnabled:
			self.ObjdBNKStatus = libmultusdBNKStatus.gRPCdBNKStatusClass(Tools)
			self.ObjdBNKStatus.gRPCSetupdBNKConnection()
		"""
		
		self.RefreshPeriodicInterval = 10.0
		self.NextRefreshPeriodic = time.time() + self.RefreshPeriodicInterval
		
		return

	def SetIntoFailSafeState(self, ProcessIsRunning):
		if self.ObjdBNKStatus:
			self.ObjdBNKStatus.gRPCSendProcessStatusmultusd(self.Ident, False, bForce = True)
		return

	def ExecuteAfterStop(self, ProcessIsRunning):
		if self.ObjdBNKStatus:
			self.ObjdBNKStatus.gRPCSendProcessStatusmultusd(self.Ident, False, bForce = True)

		return

	def ExecuteAfterStart(self, ProcessIsRunning):
		if self.ObjdBNKStatus:
			self.ObjdBNKStatus.gRPCSendProcessStatusmultusd(self.Ident, ProcessIsRunning, bForce = True)

		return

	def ExecutePeriodic(self, ProcessIsRunning):
		if self.ObjdBNKStatus:
			Timestamp = time.time()
			if Timestamp >= self.NextRefreshPeriodic:
				self.ObjdBNKStatus.gRPCSendProcessStatusmultusd(self.Ident, ProcessIsRunning, bForce = False)
				self.NextRefreshPeriodic = time.time() + self.RefreshPeriodicInterval

		return
############################################################################################################

class multusOVPNConfigClass(multusdBasicConfigfileStuff.ClassBasicConfigfileStuff):
	def __init__(self, ConfigFile):
		## initialize the parent class
		multusdBasicConfigfileStuff.ClassBasicConfigfileStuff.__init__(self)

		self.ConfigFile = ConfigFile
		self.SoftwareVersion = "20"
		
		return

	def ReadConfig(self):
		# config fuer die zu nutzenden Dateien
		ConfVorhanden = os.path.isfile(self.ConfigFile)

		if ConfVorhanden == True:
			config = configparser.ConfigParser()
			config.read(self.ConfigFile, encoding='utf-8')
			self.ConfigVersion = self.__assignStr__(config.get('ConfigVersion', 'Value'))

			self.OVPNCheckEnable = self.__assignBool__(config.get('OVPNCheckEnable', 'Value'))
			self.OVPNCheckInterval = self.__assignInt__(config.get('OVPNCheckInterval', 'Value'))
			self.OVPNCheckAdresses =  self.__assignStrArray__(config.get('OVPNCheckAdresses', 'Value'))
			self.OVPNCheckResultPort = self.__assignInt__(config.get('OVPNCheckResultPort', 'Value'))

		else:

			print ("No config file .. exiting")
			return False

		print ("multusOVPN started and read in its parameters")
		print ("OVPN Check adresses: " + str(self.OVPNCheckAdresses))
		
		return True

	# 2020-06-01	
	def ReadJsonConfig(self, ObjmultusdTools, ObjmultusdJsonConfig, Ident, Instance = 0):
		bSuccess = False
		try: 
			Timeout = 5
			url = ObjmultusdJsonConfig.JsonSingleModuleURL + Ident
			print ("We get the Json process config form url: " + url)
			with urllib.request.urlopen(url , timeout = Timeout) as url:
				ConfigData = json.loads(url.read().decode())

			#print (ConfigData)
			for (ModuleKey, ModuleValue) in ConfigData.items():
				if ModuleKey == "Instances":
					# We walk through the instaces looking for the required one	
					InstanceCounter = 0
					for SingleInstance in ModuleValue:
						if InstanceCounter == Instance:
							print ("We found the parameters of this process: " + str(SingleInstance))
							self.ConfigVersion = SingleInstance['ConfigVersion']
							self.OVPNCheckEnable = bool(int(SingleInstance['OVPNCheckEnable']))
							self.OVPNCheckInterval = int(SingleInstance['OVPNCheckInterval'])
							Adresses = SingleInstance['OVPNCheckAdresses']
							self.OVPNCheckAdresses =  Adresses.split(',')
							self.OVPNCheckResultPort = int(SingleInstance['OVPNCheckResultPort'])

							break

						InstanceCounter += 1

			bSuccess = True
		except:
			ErrorString = ObjmultusdTools.FormatException()
			LogString = "Read in Json Process config failed with Error: " + ErrorString
			print(LogString)
			
		return bSuccess


class OVPNConnectionCheckClass(object):
	def __init__(self, ObjmultusOpenVPNCheckConfig, ObjmultusdTools):

		self.ProcessHealthStatus = False

		self.ObjmultusOpenVPNCheckConfig = ObjmultusOpenVPNCheckConfig
		self.ObjmultusdTools = ObjmultusdTools

		self.OVPNConnectionStatus = libmultusLANWANCheck.ConnectionStatusClass()

		return

	def runOVPNCheck(self, OVPNCheckAdresses):
		print ("Run OVPNCheck")
		
		self.OVPNConnectionStatus.TimestampLastCheck = time.time()
		LocalStatus = None
		
		for ServerToCheck in OVPNCheckAdresses:
			LocalStatus = False
			print ("Now Checking against server: " + ServerToCheck)
			RV = subprocess.call(["/bin/ping", "-c 4",  ServerToCheck])
			if RV == 0:
				LocalStatus = True
				self.OVPNConnectionStatus.TimestampLastOK = time.time()

			break

		self.OVPNConnectionStatus.ConnectionStatus = LocalStatus
		return
 
class gRPCServiceServicer(LANWANOVPNCheck_pb2_grpc.gRPCServiceServicer):

	def __init__(self, ObjmultusdTools, ObjConnectionChecks):

		self.ObjmultusdTools = ObjmultusdTools
		
		self.OVPNcount = 0

		self.TestTimestamp = 0.0

		self.ObjConnectionChecks = ObjConnectionChecks
		return

	def gRPCGetmultusLANStatus(self, request, contect):
		result= {'ProcessOK': self.ObjConnectionChecks.ProcessHealthStatus}
		return LANWANOVPNCheck_pb2.ProcessStatusMessagemultusLAN(**result)

	def gRPCGetOVPNStatus(self, request, context):

		# get the string from the incoming request
		ReceivedString = request.RequestMessageMemberString
		print ("Received from Client: " + ReceivedString)
 	
		OVPNStatus = self.ObjConnectionChecks.OVPNConnectionStatus

		self.OVPNcount = self.OVPNcount + 1
 	
		result = {'TimestampLastCheck': OVPNStatus.TimestampLastCheck, 'TimestampLastOK': OVPNStatus.TimestampLastOK , 'ConnectionStatus': OVPNStatus.ConnectionStatus, 'count': self.OVPNcount, 'ValidStatus': True}
 
		return LANWANOVPNCheck_pb2.ResponseMessage(**result)

class gRPCOperateClass(object):
	def __init__(self, ObjmultusOpenVPNCheckConfig, ObjmultusdTools):

		self.ObjmultusOpenVPNCheckConfig = ObjmultusOpenVPNCheckConfig
		self.ObjmultusdTools = ObjmultusdTools

		self.KeepThreadRunning = True
		
		self.ObjOVPNConnectionChecks = OVPNConnectionCheckClass(ObjmultusOpenVPNCheckConfig, ObjmultusdTools)

		return

	def __del__(self):
		self.ObjdBNKStatus.gRPCSendProcessStatusClient(self.ObjmultusOpenVPNCheckConfig.Ident, False, bForce = True)
		return

	def RungRPCServer(self, multusdPingInterval, periodic):
		TimestampNextmultusdPing = time.time()

		TimestampNextOVPNCheck = time.time()
		
		# declare a server object with desired number
		# of thread pool workers.
		self.gRPCServer = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
 
		# This line can be ignored
		LANWANOVPNCheck_pb2_grpc.add_gRPCServiceServicer_to_server(gRPCServiceServicer(self.ObjmultusdTools, self.ObjOVPNConnectionChecks),self.gRPCServer)
 
		# bind the server to the port defined above
		self.gRPCServer.add_insecure_port('[::]:{}'.format(self.ObjmultusOpenVPNCheckConfig.OVPNCheckResultPort))
 
		# start the server
		self.gRPCServer.start()
		self.ObjmultusdTools.logger.debug('gRPCService Server running ...')

		OldProcessHealthStatus = self.ObjOVPNConnectionChecks.ProcessHealthStatus
		self.ObjdBNKStatus = None

		"""
		if self.ObjmultusOpenVPNCheckConfig.dBNKEnabled:
			self.ObjdBNKStatus = libmultusdBNKStatus.gRPCdBNKStatusClass(self.ObjmultusdTools)
			self.ObjdBNKStatus.gRPCSetupdBNKConnection()
		"""
	
		while self.KeepThreadRunning:
			# 2020-01-01
			# the loop shall not sleep longer than 1 second.. otherwise the handling in the stop procedure gets too slow
			SleepingTime = multusdPingInterval
			if multusdPingInterval > 1.0:
				SleepingTime = 1.0
			#self.ObjmultusdTools.logger.debug('gRPCService while loop, SleepingTime: ' + str(SleepingTime))

			Timestamp = time.time()
			if periodic and Timestamp >= TimestampNextmultusdPing:
				periodic.SendPeriodicMessage()
				TimestampNextmultusdPing = time.time() + multusdPingInterval
								
				if periodic.WeAreOnError:
					self.ObjmultusdTools.logger.debug("Error connecting to multusd... we stop running")
					self.KeepThreadRunning = False

			if self.ObjmultusOpenVPNCheckConfig.OVPNCheckEnable:
				Timestamp = time.time()
				if Timestamp >= TimestampNextOVPNCheck:
					self.ObjOVPNConnectionChecks.runOVPNCheck(self.ObjmultusOpenVPNCheckConfig.OVPNCheckAdresses)
					TimestampNextOVPNCheck = Timestamp + self.ObjmultusOpenVPNCheckConfig.OVPNCheckInterval
					SleepingTime = 0.0

			## the most important assignment, which is evaluated by dBNK
			self.ObjOVPNConnectionChecks.ProcessHealthStatus = self.ObjOVPNConnectionChecks.OVPNConnectionStatus.ConnectionStatus
			if self.ObjmultusOpenVPNCheckConfig.dBNKEnabled and OldProcessHealthStatus != self.ObjOVPNConnectionChecks.ProcessHealthStatus:
				self.ObjdBNKStatus.gRPCSendProcessStatusClient(self.ObjmultusOpenVPNCheckConfig.Ident, self.ObjOVPNConnectionChecks.ProcessHealthStatus, bForce = True)
				OldProcessHealthStatus = self.ObjOVPNConnectionChecks.ProcessHealthStatus
			elif self.ObjmultusOpenVPNCheckConfig.dBNKEnabled:
				self.ObjdBNKStatus.gRPCSendProcessStatusClient(self.ObjmultusOpenVPNCheckConfig.Ident, self.ObjOVPNConnectionChecks.ProcessHealthStatus, bForce = False)
			time.sleep (SleepingTime)

		self.ObjmultusdTools.logger.debug('gRPCService Server Stopped ...')

