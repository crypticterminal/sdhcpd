import struct, socket, IN

from pydhcplib.dhcp_packet import *
from pydhcplib.dhcp_network import DhcpServer as _DhcpServer
from server.types.parser import parse_dhcp_option, parse_ipv4_range_collection
from server.types import IPv4, MAC, ByteObject

from server.ipv4 import IPLeaseManager, LeaseError

DEFAULT_SERVER_PORT = 67
DEFAULT_CLIENT_PORT = 68
DEFAULT_LISTEN_ADDRESS = "0.0.0.0"

class DhcpServer(_DhcpServer):

    def __init__(self, listen_interface, backends):
        _DhcpServer.__init__(
                self, \
                DEFAULT_LISTEN_ADDRESS, \
                DEFAULT_CLIENT_PORT, \
                DEFAULT_SERVER_PORT \
                )
        self.BindToDevice(listen_interface)
        self.backends = backends
        self.ip_lease_manager = IPLeaseManager("lease.db")

    def BindToDevice(self, device) :
        self.dhcp_socket.setsockopt(socket.SOL_SOCKET,IN.SO_BINDTODEVICE,struct.pack("5s", device))

    def _get_ipv4_range_collection(self, offer_options=dict()):
        """Returns an AddressRangeCollection"""
        network = offer_options.pop("network", None)
        subnet_mask = offer_options.get("subnet_mask", None)
        network_prefix = offer_options.pop("network_prefix", None)
        ip_ranges_str = offer_options.pop("ip_range", None)
        if ip_ranges_str:
            return parse_ipv4_range_collection(ip_ranges_str)
        elif network:
            raise NotImplementedError
        elif subnet_mask and network_prefix:
            raise NotImplementedError
        raise Exception("Cannot determine network info for client. Missing prefix or subnet information")

    def _calculate_entry_options(self, mac_str):
        joined_offer_options = dict()
        for backend in self.backends:
            entry_options = backend.query_options(mac_str, joined_offer_options)
            if not entry_options:
                continue
            joined_offer_options.update(entry_options)
        return joined_offer_options

    def _set_packet_options(self, packet, options):
        for k, v in options.iteritems():
            option_name, value = parse_dhcp_option(k, v)
            packet.SetOption(option_name, value)

    def _get_requested_ip_from_packet(self, packet):
        for attr in ('ciaddr', 'request_ip_address'):
            if sum(packet.GetOption(attr)):
                requested_ip = IPv4.from_list(packet.GetOption(attr))
                return requested_ip
        return None

    def HandleDhcpDiscover(self, packet):
        mac = MAC.from_list(packet.GetHardwareAddress())
        print "DISCOVER: %s" % (str(mac), )
        entry_options = self._calculate_entry_options(str(mac))
        ipv4_range_collection = self._get_ipv4_range_collection(entry_options)
        self._set_packet_options(packet, entry_options)
        backend_ip = entry_options.get('yiaddr', None)
        requested_ip = self._get_requested_ip_from_packet(packet)
        ip = None
        if backend_ip:
            ip = IPv4.from_list(backend_ip)
            self.ip_lease_manager.reallocate_ip_address(ip)
            print "DISCOVER: %s gets static ip: %s" % (str(mac), str(ip), )
        else:
            ip = self.ip_lease_manager.allocate_ip_address(ipv4_range_collection, mac, requested_ip=requested_ip)
            print "DISCOVER: %s requested ip %s, giving %s" % (str(mac), str(requested_ip), str(ip), )
        packet.SetOption('yiaddr', list(ip))
        packet.TransformToDhcpOfferPacket()
        print "DISCOVER: Sent OFFER to %s" % (str(mac), )
        self.SendDhcpPacketTo(packet, "255.255.255.255", 68)

    def HandleDhcpRequest(self, packet):
        mac = MAC.from_list(packet.GetHardwareAddress())
        request_ip = self._get_requested_ip_from_packet(packet) or \
                     IP.from_list(packet.GetOption('yiaddr'))
        print "REQUEST: %s requested %s" % (str(mac), str(request_ip), )
        if sum(packet.GetOption('giaddr')):
            dest_relay_or_gateway = str(IP.from_list(packet.GetOption('giaddr')))
        else:
            dest_relay_or_gateway = "255.255.255.255"
        lease_time = 30000
        entry_options = self._calculate_entry_options(str(mac))
        ipv4_range_collection = self._get_ipv4_range_collection(entry_options)
        try:
            if not self.ip_lease_manager.was_last_leased_to(request_ip, mac):
                print "REQUEST: ERROR: %s requested ip not leased to him: %s" % (str(mac), str(request_ip), )
                packet.TransformToDhcpNackPacket()
                print "REQUEST: Sent DENY to %s" % (str(mac), )
                self.SendDhcpPacketTo(packet, dest_relay_or_gateway, 68)
                return
            self.ip_lease_manager.lease_ip_address(request_ip, mac, lease_time)
        except LeaseError as e:
            print "REQUEST: ERROR: " + str(e)
            return
        self._set_packet_options(packet, entry_options)
        packet.SetOption('yiaddr', list(request_ip))
        packet.TransformToDhcpAckPacket()
        print "REQUEST: Sent ACK to %s" % (str(mac), )
        self.SendDhcpPacketTo(packet, dest_relay_or_gateway, 68)

    def HandleDhcpDecline(self, packet):
        mac = MAC.from_list(packet.GetHardwareAddress())
        print "DECLINE: from %s" % (str(mac), )
        self.ip_lease_manager.delete_lease(mac=mac)

    def HandleDhcpRelease(self, packet):
        mac = MAC.from_list(packet.GetHardwareAddress())
        print "RELEASE: from %s" % (str(mac), )
        self.ip_lease_manager.delete_lease(mac=mac)

    def HandleDhcpInform(self, packet):
        mac = MAC.from_list(packet.GetHardwareAddress())
        print "GOT: INFORM from " + str(mac)
        entry_options = self._calculate_entry_options(str(mac))
        ipv4_range_collection = self._get_ipv4_range_collection(entry_options)
        self._set_packet_options(packet, entry_options)
        client_lease = self.ip_lease_manager.get_lease(mac=mac)
        if not client_lease:
            return None
        ip = IPv4.from_str(client_lease.ip_str)
        packet.SetOption('yiaddr', list(ip))
        packet.TransformToDhcpAckPacket()
        dest_relay_or_gateway = None
        if sum(packet.GetOption('giaddr')):
            dest_relay_or_gateway = str(IP.from_list(packet.GetOption('giaddr')))
        else:
            dest_relay_or_gateway = "255.255.255.255"
        print "SEND: ACK"
        print packet.str()
        self.SendDhcpPacketTo(packet, dest_relay_or_gateway, 68)
        print packet.str()