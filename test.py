import re
import time
from subprocess import Popen, PIPE, STDOUT
from pydhcplib.dhcp_packet import *
from pydhcplib.dhcp_network import *

from backend.ldapbackend import LDAPBackend
from backend.dummy import DummyBackend
from server.dhcp import IPLeaseManager

netopt = {'client_listen_port':"68",
          'server_listen_port':"67",
          'listen_address':"0.0.0.0"}

############# HELPERS
def parse_backend_options(options_filepath):
    options = dict()
    options_file = file(options_filepath)
    for line in options_file.readlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        option_name, option_value = map(lambda x: x.strip(), line.split(":", 1))
        if options.has_key(option_name):
            options[option_name] += " " + option_value
        else:
            options[option_name] = option_value
    options_file.close()
    # TODO Use DEBUG option
    for option_name, option_value in options.iteritems():
        print "BACKEND CONFIG: %s = %s" % (option_name, option_value)
    return options


class Server(DhcpServer):
    def __init__(self, dhcp_server_options, backends):
        DhcpServer.__init__(self,dhcp_server_options["listen_address"],
                            dhcp_server_options["client_listen_port"],
                            dhcp_server_options["server_listen_port"])
        self.backends = backends
        self.ip_lease_manager = IPLeaseManager("lease.db")

    def HandleDhcpDiscover(self, packet):
        print "Got discover!"
        joined_offer_options = dict()
        subnet = None
        netmask = None
        for backend in self.backends:
            backend_entry = backend.query_entry(packet)
            if not backend_entry:
                continue
            joined_offer_options.update(backend_entry.options)
            subnet = backend_entry.subnet or subnet
            netmask = backend_entry.netmask or netmask
        offer_packet = DhcpPacket()
        offer_packet.SetMultipleOptions(joined_offer_options)
        offer_packet.TransformToDhcpOfferPacket()
        print "Sending offer:"
        print offer_packet.str()        
        self.SendDhcpPacketTo(offer_packet, "255.255.255.255", 68)

    def HandleDhcpRequest(self, packet):
        print "Got request:"
        print packet.str()
        print "Sending ACK:"
        packet.TransformToDhcpAckPacket()
        self.SendDhcpPacketTo(packet, "255.255.255.255", 68)

    def HandleDhcpDecline(self, packet):
        print packet.str()        

    def HandleDhcpRelease(self, packet):
        print packet.str()        

    def HandleDhcpInform(self, packet):
        print packet.str()

ldap_backend = LDAPBackend(parse_backend_options("ldap_backend.conf"))
test_backend = DummyBackend()
server = Server(netopt, [ldap_backend,test_backend])

while True :
    server.GetNextDhcpPacket()