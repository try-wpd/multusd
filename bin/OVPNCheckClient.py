#!/usr/bin/env python3
#
# gRPC sample... 
# Karl Keusgen
# 2019-11-24

import grpc
import sys

sys.path.append('/multus/lib/proto')
import LANWANOVPNCheck_pb2
import LANWANOVPNCheck_pb2_grpc
 
class gRPCServiceClient(object):
    """
    Client for accessing the gRPC functionality
    """
 
    def __init__(self):
        # configure the host and the
        # the port to which the client should connect
        # to.
        self.host = 'localhost'
        self.server_port = 46002
 
        # instantiate a communication channel
        self.channel = grpc.insecure_channel('{}:{}'.format(self.host, self.server_port))
 
        # bind the client to the server channel
        self.stub = LANWANOVPNCheck_pb2_grpc.gRPCServiceStub(self.channel)
 
    def GetOVPNStatus(self, message):
        gRPCRequestMessage =LANWANOVPNCheck_pb2.RequestMessage(RequestMessageMemberString = message)
        return self.stub.gRPCGetOVPNStatus(gRPCRequestMessage)

if __name__ == "__main__":

	curr_client = gRPCServiceClient()
	RequestMessage = curr_client.GetOVPNStatus('Get OVPN Status')
	print (str(RequestMessage.ConnectionStatus))
	print (str(RequestMessage))


