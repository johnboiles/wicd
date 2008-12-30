#!/usr/bin/env python

""" networking - Provides wrappers for common network operations

This module provides wrappers of the common network tasks as well as
threads to perform the actual connecting to networks.

class Controller() -- Parent class to Wireless and Wired
class ConnectThread() -- Parent class to WirelessConnectThread and
    WiredConnectThread
class Wireless() -- Wrapper for various wireless functions
class Wired() -- Wrapper for various wired functions
class WirelessConnectThread() -- Connection thread for wireless
    interface
class WiredConnectThread() -- Connection thread for wired
    interface

"""

#
#   Copyright (C) 2007 - 2008 Adam Blackburn
#   Copyright (C) 2007 - 2008 Dan O'Reilly
#   Copyright (C) 2007 - 2008 Byron Hillis
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License Version 2 as
#   published by the Free Software Foundation.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

#
# Much thanks to wieman01 for help and support with various types of encyption.
# Also thanks to foxy123, yopnono, and the many others who reported bugs helped
# and helped keep this project moving.
#

import re
import time
import threading
import thread

# wicd imports 
import misc
import wpath
from backend import BackendManager

if __name__ == '__main__':
    wpath.chdir(__file__)

BACKEND = None
BACKEND_MGR = BackendManager()

def abortable(func):
    """ Mark a method in a ConnectionThread as abortable. 
    
    This decorator runs a check that will abort the connection thread
    if necessary before running a given method.
    
    """
    def wrapper(self, *__args, **__kargs):
        self.abort_if_needed()
        return func(self, *__args, **__kargs)
    
    wrapper.__name__ = func.__name__
    wrapper.__dict__ = func.__dict__
    wrapper.__doc__ = func.__doc__
    return wrapper

def get_backend_list():
    """ Returns a list of available backends. """
    if BACKEND_MGR:
        return BACKEND_MGR.get_available_backends()
    else:
        return [""]
    
def get_backend_update_interval():
    if BACKEND_MGR:
        return BACKEND_MGR.get_update_interval()
    else:
        return 5  # Seconds, this should never happen though.
    
def get_current_backend():
    if BACKEND_MGR:
        return BACKEND_MGR.get_current_backend()
    else:
        return None
    
def get_backend_description(backend_name):
    return BACKEND_MGR.get_backend_description(backend_name)

def get_backend_description_dict():
    d = {}
    for be in get_backend_list():
        if be:
            d[be] = get_backend_description(be)
    return d
    
class Controller(object):
    """ Parent class for the different interface types. """
    def __init__(self):
        """ Initialise the class. """
        self.global_dns_1 = None
        self.global_dns_2 = None
        self.global_dns_3 = None
        self.global_search_dom = None
        self._dhcp_client = None
        self._flush_tool = None
        self._debug = None
        self._backend = None
        self.connecting_thread = None
        self.before_script = None
        self.after_script = None
        self.disconnect_script = None
        self.driver = None
        self.iface = None
        self.backend_manager = BackendManager()   
    
    def set_debug(self, value):
        self._debug = value
        if self.iface:
            self.iface.SetDebugMode(value)
    def get_debug(self): return self._debug
    debug = property(get_debug, set_debug)
    
    def set_dhcp_client(self, value):
        self._dhcp_client = value
        if self.iface:
            self.iface.DHCP_CLIENT = value
            self.iface.CheckDHCP()
            
    def get_dhcp_client(self): return self._dhcp_client
    dhcp_client = property(get_dhcp_client, set_dhcp_client)
    
    def set_flush_tool(self, value):
        self._flush_tool = value
        if self.iface:
            self.iface.flush_tool = value
    def get_flush_tool(self): return self._flush_tool
    flush_tool = property(get_flush_tool, set_flush_tool)
    
    def LoadBackend(self, backend_name):
        """ Load the given networking backend. """
        global BACKEND
        if backend_name == self._backend:
            return
        self._backend = BACKEND_MGR.load_backend(backend_name)
        BACKEND = self._backend
        
    def NeedsExternalCalls(self):
        """ Returns true if the loaded backend needs external calls. """
        if self._backend:
            return self._backend.NeedsExternalCalls()
        else:
            return True
        
    def StopDHCP(self):
        return BACKEND.StopDHCP()
    
    def GetIP(self, ifconfig=""):
        """ Get the IP of the interface.

        Returns:
        The IP address of the interface in dotted notation.

        """
        return self.iface.GetIP(ifconfig)

    def Disconnect(self):
        """ Disconnect from the network. """
        iface = self.iface
        if self.disconnect_script != None:
            print 'Running wired disconnect script'
            misc.Run(self.disconnect_script)

        iface.ReleaseDHCP()
        iface.SetAddress('0.0.0.0')
        iface.Down()
        iface.Up()
        
    def IsUp(self):
        """ Calls the IsUp method for the wired interface. 
        
        Returns:
        True if the interface is up, False otherwise.
        
        """
        return self.iface.IsUp()
    
    def EnableInterface(self):
        """ Puts the interface up.
        
        Returns:
        True if the interface was put up succesfully, False otherwise.
        
        """
        return self.iface.Up()
    
    def DisableInterface(self):
        """ Puts the interface down.
        
        Returns:
        True if the interface was put down succesfully, False otherwise.
        
        """
        return self.iface.Down()


class ConnectThread(threading.Thread):
    """ A class to perform network connections in a multi-threaded way.

    Useless on it's own, this class provides the generic functions
    necessary for connecting using a separate thread.
    
    """

    is_connecting = None
    connecting_thread = None
    should_die = False
    lock = thread.allocate_lock()

    def __init__(self, network, interface_name, before_script, after_script, 
                 disconnect_script, gdns1, gdns2, gdns3, gsearch_dom, 
                 iface, debug):
        """ Initialise the required object variables and the thread.

        Keyword arguments:
        network -- the network to connect to
        wireless -- name of the wireless interface
        wired -- name of the wired interface
        before_script -- script to run before bringing up the interface
        after_script -- script to run after bringing up the interface
        disconnect_script -- script to run after disconnection
        gdns1 -- global DNS server 1
        gdns2 -- global DNS server 2
        gdns3 -- global DNS server 3
        debug -- debug mode status

        """
        threading.Thread.__init__(self)
        self.network = network
        self.is_connecting = False
        self.is_aborted = False
        self.connect_result = None
        self.before_script = before_script
        self.after_script = after_script
        self.disconnect_script = disconnect_script
        self._should_die = False
        self.abort_reason = ""
        self.connect_result = ""

        self.global_dns_1 = gdns1
        self.global_dns_2 = gdns2
        self.global_dns_3 = gdns3
        self.global_search_dom = gsearch_dom
        
        self.iface = iface

        self.connecting_message = None
        self.debug = debug
        
        self.SetStatus('interface_down')
        
    def set_should_die(self, val):
        self.lock.acquire()
        try:
            self._should_die = val
        finally:
            self.lock.release()
    def get_should_die(self): return self._should_die
    should_die = property(get_should_die, set_should_die)

    def SetStatus(self, status):
        """ Set the threads current status message in a thread-safe way.

        Keyword arguments:
        status -- the current connection status

        """
        self.lock.acquire()
        try:
            self.connecting_message = status
        finally:
            self.lock.release()


    def GetStatus(self):
        """ Get the threads current status message in a thread-safe way.

        Returns:
        The current connection status.

        """
        self.lock.acquire()
        try:
            message = self.connecting_message
        finally:
            self.lock.release()
        return message
    
    @abortable
    def reset_ip_addresses(self, iface):
        """ Resets the IP addresses for both wired/wireless interfaces.
        
        Sets a false ip so that when we set the real one, the correct
        routing entry is created.
        
        """
        print 'Setting false IP...'
        self.SetStatus('resetting_ip_address')
        iface.SetAddress('0.0.0.0')
    
    @abortable
    def put_iface_down(self, iface):
        """ Puts the given interface down. """
        print 'Putting interface down'
        self.SetStatus('interface_down')
        iface.Down()
        
    @abortable
    def run_script_if_needed(self, script, msg):
        """ Execute a given script if needed.
        
        Keyword arguments:
        script -- the script to execute, or None/'' if there isn't one.
        msg -- the name of the script to display in the log.
        
        """
        if script:
            print 'Executing %s script' % (msg)
            misc.ExecuteScript(script)
        
    @abortable
    def flush_routes(self, iface):
        """ Flush the routes for both wired/wireless interfaces. """
        self.SetStatus('flushing_routing_table')
        print 'Flushing the routing table...'
        iface.FlushRoutes()
        
    @abortable
    def set_broadcast_address(self, iface):
        """ Set the broadcast address for the given interface. """
        if not self.network.get('broadcast') == None:
            self.SetStatus('setting_broadcast_address')
            print 'Setting the broadcast address...' + self.network['broadcast']
            iface.SetAddress(broadcast=self.network['broadcast'])
        
    @abortable            
    def set_ip_address(self, iface):
        """ Set the IP address for the given interface. 
        
        Assigns a static IP if one is requested, otherwise calls DHCP.
        
        """
        if self.network.get('ip'):
            self.SetStatus('setting_static_ip')
            print 'Setting static IP : ' + self.network['ip']
            iface.SetAddress(self.network['ip'], self.network['netmask'])
            print 'Setting default gateway : ' + self.network['gateway']
            iface.SetDefaultRoute(self.network['gateway'])
        else:
            # Run dhcp...
            self.SetStatus('running_dhcp')
            print "Running DHCP"
            dhcp_status = iface.StartDHCP()
            if dhcp_status in ['no_dhcp_offers', 'dhcp_failed']:
                self.abort_connection(dhcp_status)
                return
        
    @abortable            
    def set_dns_addresses(self):
        """ Set the DNS address(es).

        If static DNS servers or global DNS servers are specified, set them.
        Otherwise do nothing.
        
        """
        if self.network.get('use_global_dns'):
            BACKEND.SetDNS(misc.Noneify(self.global_dns_1),
                             misc.Noneify(self.global_dns_2), 
                             misc.Noneify(self.global_dns_3),
                             misc.Noneify(self.global_search_dom))
        elif self.network.get('use_static_dns') and (self.network.get('dns1') or
                    self.network.get('dns2') or self.network.get('dns3')):
            self.SetStatus('setting_static_dns')
            BACKEND.SetDNS(self.network.get('dns1'),
                                 self.network.get('dns2'),
                                 self.network.get('dns3'),
                                 self.network.get('search_domain'))

    @abortable        
    def release_dhcp_clients(self, iface):
        """ Release all running dhcp clients. """
        print "Releasing DHCP leases..."
        iface.ReleaseDHCP()
        
    @abortable        
    def stop_dhcp_clients(self, iface):
        """ Stop and running DHCP clients. """
        print 'Stopping DHCP clients'
        BACKEND.StopDHCP()
        
    def connect_aborted(self, reason):
        """ Sets the thread status to aborted in a thread-safe way.
        
        Sets the status to aborted, and also delays returning for
        a few seconds to make sure the message is readable
        
        """
        if self.abort_reason:
            reason = self.abort_reason
        self.connecting_message = reason
        self.is_aborted = True
        self.connect_result = reason
        self.is_connecting = False
        print 'exiting connection thread'
        
    def abort_connection(self, reason=""):
        """ Schedule a connection abortion for the given reason. """
        self.abort_reason = reason
        self.should_die = True
        
    def abort_if_needed(self):
        """ Abort the thread is it has been requested. """
        self.lock.acquire()
        try:
            if self._should_die:
                self.connect_aborted('aborted')
                thread.exit()
        finally:
            self.lock.release()
        
    @abortable            
    def put_iface_up(self, iface):
        """ Bring up given interface. """
        print 'Putting interface up...'
        self.SetStatus('interface_up')
        iface.Up()


class Wireless(Controller):
    """ A wrapper for common wireless interface functions. """

    def __init__(self):
        """ Initialize the class. """
        Controller.__init__(self)
        self._wpa_driver = None
        self._wireless_interface = None
        self.wiface = None 
        
    def set_wireless_iface(self, value):
        self._wireless_interface = value
        if self.wiface:
            self.wiface.SetInterface(value)
    def get_wireless_iface(self): return self._wireless_interface
    wireless_interface = property(get_wireless_iface, set_wireless_iface) 
        
    def set_wpa_driver(self, value):
        self._wpa_driver = value
        if self.wiface:
            self.SetWPADriver(value)
    def get_wpa_driver(self): return self._wpa_driver
    wpa_driver = property(get_wpa_driver, set_wpa_driver)
    
    def set_iface(self, value):
        self.wiface = value
    def get_iface(self):
        return self.wiface
    iface = property(get_iface, set_iface)
        
    def LoadBackend(self, backend):
        """ Load a given backend. 

        Load up a backend into the backend manager and associate with
        the networking interface.
        
        """
        Controller.LoadBackend(self, backend)
        if self._backend:
            self.wiface = self._backend.WirelessInterface(self.wireless_interface,
                                                    self.debug, self.wpa_driver)

    def Scan(self, essid=None):
        """ Scan for available wireless networks.

        Keyword arguments:
        essid -- The essid of a hidden network

        Returns:
        A list of available networks sorted by strength.

        """
        def comp(x, y):
            if x.has_key('quality'):
                if x['quality'] > y['quality']:
                    return 1
                elif x['quality'] < y['quality']:
                    return -1
                else:
                    return 0
            else:
                if x['strength'] < y['strength']:
                    return 1
                elif x['strength'] > y['strength']:
                    return -1
                else:
                    return 0
                
        if not self.wiface: return []
        
        wiface = self.wiface

        # Prepare the interface for scanning
        wiface.Up()

        # If there is a hidden essid then set it now, so that when it is
        # scanned it will be recognized.
        essid = misc.Noneify(essid)
        if essid is not None:
            print 'Setting hidden essid' + essid
            wiface.SetEssid(essid)

        aps = wiface.GetNetworks()
        aps.sort(cmp=comp, reverse=True)
        
        return aps

    def Connect(self, network, debug=False):
        """ Spawn a connection thread to connect to the network.

        Keyword arguments:
        network -- network to connect to

        """
        if not self.wiface: return False
        
        self.connecting_thread = WirelessConnectThread(network,
            self.wireless_interface, self.wpa_driver, self.before_script,
            self.after_script, self.disconnect_script, self.global_dns_1,
            self.global_dns_2, self.global_dns_3, self.global_search_dom,
            self.wiface, debug)
        self.connecting_thread.setDaemon(True)
        self.connecting_thread.start()
        return True

    def GetSignalStrength(self, iwconfig=""):
        """ Get signal strength of the current network.

        Returns:
        The current signal strength.

        """
        return self.wiface.GetSignalStrength(iwconfig)

    def GetDBMStrength(self, iwconfig=""):
        """ Get the dBm signal strength of the current network.

        Returns:
        The current dBm signal strength.

        """
        return self.wiface.GetDBMStrength(iwconfig)

    def GetCurrentNetwork(self, iwconfig=""):
        """ Get current network name.

        Returns:
        The name of the currently connected network.

        """
        return self.wiface.GetCurrentNetwork(iwconfig)
    
    def GetBSSID(self):
        """ Get the BSSID of the current access point. 
        
        Returns:
        The MAC Adress of the active access point as a string, or
        None the BSSID can't be found.
        
        """
        return self.wiface.GetBSSID()

    def GetIwconfig(self):
        """ Get the out of iwconfig. """
        return self.wiface.GetIwconfig()
    
    def GetWpaSupplicantDrivers(self, drivers):
        """ Returns all valid wpa_supplicant drivers in a list. """
        return [driver for driver in drivers if 
                BACKEND.IsValidWpaSuppDriver(driver)]
    
    def StopWPA(self):
        return self.wiface.StopWPA()

    def CreateAdHocNetwork(self, essid, channel, ip, enctype, key,
            enc_used):
        """ Create an ad-hoc wireless network.

        Keyword arguments:
        essid -- essid of the ad-hoc network
        channel -- channel of the ad-hoc network
        ip -- ip of the ad-hoc network
        enctype -- unused
        key -- key of the ad-hoc network
        enc_used -- encrytion enabled on ad-hoc network

        """
        wiface = self.wiface
        print 'Creating ad-hoc network'
        print 'Killing dhclient and wpa_supplicant'
        BACKEND.StopDHCP()
        wiface.StopWPA()
        print 'Putting wireless interface down'
        wiface.Down()
        print 'Setting mode, channel, and essid'
        wiface.SetMode('ad-hoc')
        wiface.SetChannel(channel)
        wiface.SetEssid(essid)
        # Right now it just assumes you're using WEP
        if enc_used:
            print 'Setting encryption key'
            wiface.SetKey(key)
        print 'Putting interface up'
        wiface.Up()
        print 'Setting IP address'
        wiface.SetAddress(ip, '255.255.255.0')

    def DetectWirelessInterface(self):
        """ Detect available wireless interfaces.

        Returns:
        The first available wireless interface.

        """
        return BACKEND.GetWirelessInterfaces()

    def GetKillSwitchStatus(self):
        """ Get the current status of the Killswitch. 
        
        Returns:
        True if the killswitch is on, False otherwise.
        
        """
        return self.wiface.GetKillSwitchStatus()

    def Disconnect(self):
        """ Disconnect the given iface.
        
        Executes the disconnect script associated with a given interface,
        Resets it's IP address, and puts the interface down then up.
        
        """
        Controller.Disconnect(self)
        self.StopWPA()
    
    def SetWPADriver(self, driver):
        """ Sets the wpa_supplicant driver associated with the interface. """
        self.wiface.SetWpaDriver(driver)

class WirelessConnectThread(ConnectThread):
    """ A thread class to perform the connection to a wireless network.

    This thread, when run, will perform the necessary steps to connect
    to the specified network.

    """

    def __init__(self, network, wireless, wpa_driver, before_script,
                 after_script, disconnect_script, gdns1, gdns2, gdns3, 
                 gsearch_dom, wiface, debug=False):
        """ Initialise the thread with network information.

        Keyword arguments:
        network -- the network to connect to
        wireless -- name of the wireless interface
        wpa_driver -- type of wireless interface
        before_script -- script to run before bringing up the interface
        after_script -- script to run after bringing up the interface
        disconnect_script -- script to run after disconnection
        gdns1 -- global DNS server 1
        gdns2 -- global DNS server 2
        gdns3 -- global DNS server 3

        """
        ConnectThread.__init__(self, network, wireless, before_script, 
                               after_script, disconnect_script, gdns1, gdns2, 
                               gdns3, gsearch_dom, wiface, debug)
        self.wpa_driver = wpa_driver


    def run(self):
        """ The main function of the connection thread.

        This function performs the necessary calls to connect to the
        specified network, using the information provided. The following
        indicates the steps taken.
        1. Run pre-connection script.
        2. Take down the interface and clean up any previous
           connections.
        3. Generate a PSK if required and authenticate.
        4. Associate with the WAP.
        5. Get/set IP address and DNS servers.

        """
        wiface = self.iface
        self.is_connecting = True
        
        # Run pre-connection script.
        self.run_script_if_needed(self.before_script, 'pre-connection')
        
        # Take down interface and clean up previous connections.
        self.put_iface_down(wiface)
        self.release_dhcp_clients(wiface)
        self.reset_ip_addresses(wiface)
        self.stop_dhcp_clients(wiface)
        self.stop_wpa(wiface)
        self.flush_routes(wiface)

        # Generate PSK and authenticate if needed.
        if self.wpa_driver != 'ralink legacy':
            self.generate_psk_and_authenticate(wiface)

        # Put interface up.
        self.SetStatus('configuring_interface')
        self.put_iface_up(wiface)
        
        # Associate.
        wiface.SetMode(self.network['mode'])
        wiface.Associate(self.network['essid'], self.network['channel'],
                         self.network['bssid'])

        # Authenticate after association for Ralink legacy cards.
        if self.wpa_driver == 'ralink legacy':
            if self.network.get('key'):
                wiface.Authenticate(self.network)
                
        # Validate Authentication.
        if self.network.get('enctype'):
            self.SetStatus('validating_authentication')
            if not wiface.ValidateAuthentication(time.time()):
                if not self.connect_result:
                    self.abort_connection('bad_pass')

        # Set up gateway, IP address, and DNS servers.
        self.set_broadcast_address(wiface)
        self.set_ip_address(wiface)
        self.set_dns_addresses()
        
        # Run post-connection script.
        self.run_script_if_needed(self.after_script, 'post-connection')

        self.SetStatus('done')
        print 'Connecting thread exiting.'
        if self.debug:
            print "IP Address is: " + str(wiface.GetIP())
        self.connect_result = "Success"
        self.is_connecting = False
        
    @abortable
    def stop_wpa(self, wiface):
        """ Stops wpa_supplicant. """
        print 'Stopping wpa_supplicant'
        wiface.StopWPA()
        
    @abortable    
    def generate_psk_and_authenticate(self, wiface):
        """ Generates a PSK and authenticates if necessary. 
        
        Generates a PSK, and starts the authentication process
        if encryption is on.
        
        """
        # Check to see if we need to generate a PSK (only for non-ralink
        # cards).
        if self.debug:
            print "enctype is %s" % self.network.get('enctype')
        if self.network.get('key') and 'wpa' in str(self.network.get('enctype')):
            self.SetStatus('generating_psk')
            print 'Generating psk...'
            self.network['psk'] = wiface.GeneratePSK(self.network)
            
            if not self.network.get('psk'):
                self.network['psk'] = self.network['key']
                print 'WARNING: PSK generation failed!  Falling back to ' + \
                      'wireless key.\nPlease report this error to the wicd ' + \
                      'developers!'
        # Generate the wpa_supplicant file...
        if self.network.get('enctype'):
            self.SetStatus('generating_wpa_config')
            print 'Attempting to authenticate...'
            wiface.Authenticate(self.network)


class Wired(Controller):
    """ A wrapper for common wired interface functions. """

    def __init__(self):
        """ Initialise the class. """
        Controller.__init__(self)
        self.wpa_driver = None
        self._link_detect = None
        self._wired_interface = None
        self.liface = None
        
    def set_link_detect(self, value):
        self._link_detect = value
        if self.liface:
            self.liface.link_detect = value
    def get_link_detect(self): return self._link_detect
    link_detect = property(get_link_detect, set_link_detect)
    
    
    def set_wired_iface(self, value):
        self._wired_interface = value
        if self.liface:
            self.liface.SetInterface(value)            
    def get_wired_iface(self): return self._wired_interface
    wired_interface = property(get_wired_iface, set_wired_iface)
    
    def set_iface(self, value):
        self.liface = value
    def get_iface(self):
        return self.liface
    iface = property(get_iface, set_iface)
    
    def LoadBackend(self, backend):
        """ Load the backend up. """
        Controller.LoadBackend(self, backend)
        if self._backend:
            self.liface = self._backend.WiredInterface(self.wired_interface,
                                                       self.debug)

    def CheckPluggedIn(self):
        """ Check whether the wired connection is plugged in.

        Returns:
        The status of the physical connection link.

        """
        return self.liface.GetPluggedIn()

    def Connect(self, network, debug=False):
        """ Spawn a connection thread to connect to the network.

        Keyword arguments:
        network -- network to connect to

        """
        if not self.liface: return False
        self.connecting_thread = WiredConnectThread(network,
            self.wired_interface, self.before_script, self.after_script,
            self.disconnect_script, self.global_dns_1, self.global_dns_2, 
            self.global_dns_3, self.global_search_dom, self.liface, debug)
        self.connecting_thread.setDaemon(True)
        self.connecting_thread.start()
        return self.connecting_thread
    
    def DetectWiredInterface(self):
        """ Attempts to automatically detect a wired interface. """
        try:
            return BACKEND.GetWiredInterfaces()[0]
        except IndexError:
            return None


class WiredConnectThread(ConnectThread):
    """ A thread class to perform the connection to a wired network.

    This thread, when run, will perform the necessary steps to connect
    to the specified network.

    """
    def __init__(self, network, wired, before_script, after_script, 
                 disconnect_script, gdns1, gdns2, gdns3, gsearch_dom, liface, 
                 debug=False):
        """ Initialise the thread with network information.

        Keyword arguments:
        network -- the network to connect to
        wireless -- name of the wireless interface
        wired -- name of the wired interface
        before_script -- script to run before bringing up the interface
        after_script -- script to run after bringing up the interface
        disconnect_script -- script to run after disconnection
        gdns1 -- global DNS server 1
        gdns2 -- global DNS server 2
        gdns3 -- global DNS server 3

        """
        ConnectThread.__init__(self, network, wired, before_script, 
                               after_script, disconnect_script, gdns1, gdns2, 
                               gdns3, gsearch_dom, liface, debug)

    def run(self):
        """ The main function of the connection thread.

        This function performs the necessary calls to connect to the
        specified network, using the information provided. The following
        indicates the steps taken.
        1. Run pre-connection script.
        2. Take down the interface and clean up any previous
           connections.
        3. Bring up the interface.
        4. Get/set IP address and DNS servers.
        5. Run post-connection script.

        """
        liface = self.iface

        self.is_connecting = True

        # Run pre-connection script.
        self.run_script_if_needed(self.before_script, 'pre-connection')
        
        # Take down interface and clean up previous connections.
        self.put_iface_down(liface)
        self.release_dhcp_clients(liface)
        self.reset_ip_addresses(liface)
        self.stop_dhcp_clients(liface)
        self.flush_routes(liface)
        
        # Bring up interface.
        self.put_iface_up(liface)
        
        # Set gateway, IP adresses, and DNS servers.
        self.set_broadcast_address(liface)
        self.set_ip_address(liface)
        self.set_dns_addresses()
        
        # Run post-connection script.
        self.run_script_if_needed(self.after_script, 'post-connection')

        self.SetStatus('done')
        print 'Connecting thread exiting.'
        if self.debug:
            print "IP Address is: " + str(liface.GetIP())
        
        self.connect_result = "Success"
        self.is_connecting = False
