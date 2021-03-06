import libperf
import libudpgen
import xenrt
import random, string, time, threading

# Expects the sequence file to set up two VMs, called 'endpoint0' and 'endpoint1'
class TCUDPGen(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCUDPGen")

    def findGuests(self):
        self.pool = self.getDefaultPool()
        if self.pool:
            self.host = self.pool.master
            self.hosts = self.pool.getHosts()
        else:
            #self.host already defined in libperf.initialiseHostList()
            self.hosts = [self.host]
        self.log(None, "hosts1=%s" % (self.hosts,))

        # any other remaining hosts not in any pools
        hostlist = xenrt.TEC().registry.hostList()
        self.log(None, "hostlist=%s" % (hostlist,))
        for h in hostlist:
            host = xenrt.TEC().registry.hostGet(h)
            if host not in self.hosts:
                self.hosts += [host]
        self.log(None, "hosts2=%s" % (self.hosts,))

        self.guests = []
        for host in self.hosts:
            self.guests = self.guests + host.guests.values()
        self.log(None, "guests=%s" % (self.guests,))

    def getGuestOrHostFromName(self, name):
        for guest in self.guests:
            if guest.getName() == name:
                self.log(None, "name=%s -> guest=%s" % (name, guest))
                return guest
        host = xenrt.TEC().registry.hostGet(name)
        self.log(None, "name=%s -> host=%s" % (name, host))
        if host:
            return host
        raise xenrt.XRTError("Failed to find guest or host with name %s" % (name,))

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        self.log(None, "parseArgs:arglist=%s" % (arglist,))
        self.npkts = libperf.getArgument(arglist, "npkts", int, 10000)
        self.size = libperf.getArgument(arglist, "size", int, 1450)
        self.tolerance = libperf.getArgument(arglist, "tolerance", int, 2)
        self.gro      = libperf.getArgument(arglist, "gro", str, "default")
        self.dopause  = libperf.getArgument(arglist, "pause", str, "off")

        # Optionally, the sequence file can specify which eth device to use in each endpoint
        self.e0dev = libperf.getArgument(arglist, "endpoint0dev", int, None)
        self.e1dev = libperf.getArgument(arglist, "endpoint1dev", int, None)

        # Optionally, the sequence file can specify IP addresses to use in each endpoint
        self.e0ip = libperf.getArgument(arglist, "endpoint0ip", str, None)
        self.e1ip = libperf.getArgument(arglist, "endpoint1ip", str, None)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

        # Populate self.guests
        self.findGuests()

        self.log(None, "prepare:arglist=%s" % (arglist,))
        # Get the two communication endpoints
        e0 = libperf.getArgument(arglist, "endpoint0", str, None)
        e1 = libperf.getArgument(arglist, "endpoint1", str, None)
        self.log(None, "endpoints: e0=%s, e1=%s" % (e0,e1))
        if not e0 or not e1:
            raise xenrt.XRTError("Failed to find an endpoint")
        self.endpoint0 = self.getGuestOrHostFromName(e0)
        self.endpoint1 = self.getGuestOrHostFromName(e1)

    def before_prepare(self, arglist=None):
        pass
        ## tag the ipv6 network to be used by VMs
        #self.host.genParamSet("network", self.ipv6_net, "other-config", "true", "xenrtvms")

    def runUDPGen(self, origin, origindev, dest, destdev, npkts, size, tolerance):

        destIP = self.getIP(dest, destdev)

        def run_tx_thread():
            # give the server a moment to start up
            time.sleep(20)
            libudpgen.run_tx(origin, destIP, npkts=npkts, size=size)

        tx_thread = threading.Thread(target=run_tx_thread)
        tx_thread.start()

        stdout, stderr = libudpgen.run_rx(dest, npkts=npkts, size=size, tolerance=tolerance)

        tx_thread.join()

        return stdout, stderr

    def hostOfEndpoint(self, endpoint):
        # Get the host object for this endpoint
        if isinstance(endpoint, xenrt.GenericGuest):
            return endpoint.host
        elif isinstance(endpoint, xenrt.GenericHost):
            return endpoint
        else:
            raise xenrt.XRTError("unrecognised endpoint %s with type %s" % (endpoint, type(endpoint)))

    def ethOfDev(self, endpoint, endpointdev):
        assert isinstance(endpoint, xenrt.GenericHost)
        return endpoint.getNIC(endpointdev)

    def setIPAddress(self, endpoint, endpointdev, ip):
        if isinstance(endpoint, xenrt.GenericGuest):
            (eth, bridge, mac, _) = endpoint.vifs[endpointdev]
            # TODO support configuring static IP in Windows guests
            endpoint.execguest("ifconfig %s %s netmask 255.255.255.0" % (eth, ip))
            endpoint.vifs[endpointdev] = (eth, bridge, mac, ip)
        elif isinstance(endpoint, xenrt.lib.xenserver.Host):
            raise xenrt.XRTError("setting IP on XenServer PIF is not yet implemented")
        elif isinstance(endpoint, xenrt.GenericHost):
            endpoint.execcmd("ifconfig %s %s netmask 255.255.255.0" % (self.ethOfDev(endpoint, endpointdev), ip))

    def getIP(self, endpoint, endpointdev=None):
        # If the device is specified then get the IP for that device
        if endpointdev is not None:
            if isinstance(endpoint, xenrt.GenericGuest):
                (_, _, _, ip) = endpoint.vifs[endpointdev]
            elif isinstance(endpoint, xenrt.lib.xenserver.Host):
                ip = endpoint.getNICAllocatedIPAddress(endpointdev)
            elif isinstance(endpoint, xenrt.GenericHost):
                ip = endpoint.execdom0("ifconfig %s | fgrep 'inet addr:' | awk '{print $2}' | awk -F: '{print $2}'" % (self.ethOfDev(endpoint, endpointdev))).strip()
        else:
            ip = endpoint.getIP()
        return ip

    def nicdevOfEndpointDev(self, endpoint, endpointdev):
        assert isinstance(endpoint, xenrt.GenericHost)
        ethdev = self.ethOfDev(endpoint, endpointdev)
        mac    = endpoint.execcmd("ifconfig %s | fgrep HWaddr | awk '{print $5}'" % (ethdev)).strip()
        return ethdev, mac

    def nicdev(self, endpoint):
        ip = self.getIP(endpoint, None)
        return self.nicdevOfIP(endpoint, ip)

    def nicdevOfIP(self, endpoint, ip):
        endpointHost = self.hostOfEndpoint(endpoint)

        # Get the device name and MAC address for a given IP address
        if endpointHost.productType == "esx":
            cmds = [
                "vmk=$(esxcfg-vmknic -l | fgrep '%s' | awk '{print $1}')" % (ip,),
                "portgroup=$(esxcli network ip interface list | grep -A 10 \"^$vmk\\$\" | fgrep \"Portgroup:\" | sed 's/^.*: //')",
                "vswitch=$(esxcli network vswitch standard portgroup list | grep \"^$portgroup \" | sed \"s/^$portgroup *//\" | awk '{print $1}')",
                "nic=$(esxcfg-vswitch -l | fgrep $vswitch | awk '{print $6}')",
                "mac=$(esxcfg-vmknic -l | fgrep '%s' | awk '{print toupper($8)}')" % (ip,),
                "echo $nic $mac",
            ]
            cmd = "; ".join(cmds)
        else:
            cmd = "ifconfig |grep -B 1 '%s'|grep HWaddr|awk '{print $1,$5}'" % (ip,)

        _dev, mac = endpoint.execcmd(cmd).split(" ")

        dev = _dev.replace("xenbr","eth")
        dev = dev.replace("virbr","eth")
        return dev, mac

    # endpoint is always a xenrt.GenericHost
    def nicinfo(self, endpoint, endpointdev=None, key_prefix=""):
        assert isinstance(endpoint, xenrt.GenericHost)
        def map2kvs(ls):return map(lambda l: l.split("="), ls)
        def kvs2dict(prefix,kvs):return dict(map(lambda (k,v): ("%s%s" % (prefix, k.strip()), v.strip()), filter(lambda kv: len(kv)==2, kvs)))
        if endpointdev is None:
            dev, mac = self.nicdev(endpoint)
        else:
            dev, mac = self.nicdevOfEndpointDev(endpoint, endpointdev)
        endpointHost = self.hostOfEndpoint(endpoint)
        ethtool   = kvs2dict("ethtool:",   map2kvs(endpoint.execcmd("ethtool %s"    % (dev,)).replace(": ","=").split("\n")))
        ethtool_i = kvs2dict("ethtool-i:", map2kvs(endpoint.execcmd("ethtool -i %s" % (dev,)).replace(": ","=").split("\n")))
        ethtool_k = kvs2dict("ethtool-k:", map2kvs(endpoint.execcmd("ethtool -k %s" % (dev,)).replace(": ","=").split("\n")))
        ethtool_P = kvs2dict("ethtool-P:", map2kvs(endpoint.execcmd("ethtool -P %s" % (dev,)).replace(": ","=").split("\n")))
        g = map2kvs(endpoint.execcmd("ethtool -g %s" % (dev,)).replace("\t","").replace(":","=").split("\n"))
        ethtool_g = {}
        ethtool_g["ethtool-g:ringmaxRX"]         = g[2][1]
        ethtool_g["ethtool-g:ringmaxRXMini"]     = g[3][1]
        ethtool_g["ethtool-g:ringmaxRXJumbo"]    = g[4][1]
        ethtool_g["ethtool-g:ringmaxTX"]         = g[5][1]
        ethtool_g["ethtool-g:ringcurRX"]     = g[7][1]
        ethtool_g["ethtool-g:ringcurRXMini"] = g[8][1]
        ethtool_g["ethtool-g:ringcurRXJumbo"]= g[9][1]
        ethtool_g["ethtool-g:ringcurTX"]     = g[10][1]
        if "ethtool-P:Permanent address" in ethtool_P:
            pa = ethtool_P["ethtool-P:Permanent address"].strip().upper()
            m  = mac.strip().upper()
            xenrt.TEC().logverbose("ethtool -i output is: %s" % (ethtool_i))
            if ethtool_i["ethtool-i:driver"] == "mlx4_en" and pa == "00:00:00:00:00:00":
                # This has been observed on CentOS 6.5, despite it working fine on XenServer with the same driver version and firmware version
                xenrt.TEC().logverbose("Permanent address of %s is zero. Not sure why, but it's not a problem." % (dev,))
            elif pa != m:
                raise xenrt.XRTError("ethtool_P permanent address '%s' is different from mac from ifconfig '%s'" % (pa, m))
        pci_id = ethtool_i["ethtool-i:bus-info"][5:]
        dev_desc = endpoint.execcmd("lspci |grep '%s'" % (pci_id,)).split("controller: ")[1]
        proc_sys_net = kvs2dict("", map2kvs(endpoint.execcmd("find /proc/sys/net/ 2>/dev/null | while read p; do echo \"$p=`head --bytes=256 $p`\"; done", timeout=600).split("\n")))
        sys_class_net = kvs2dict("", map2kvs(endpoint.execcmd("find /sys/class/net/*/* 2>/dev/null | while read p; do echo \"$p=`head --bytes=256 $p`\"; done", timeout=600).split("\n")))
        sys_devices = kvs2dict("", map2kvs(endpoint.execcmd("find /sys/devices/system/cpu/ 2>/dev/null | while read p; do echo \"$p=`head --bytes=256 $p`\"; done", timeout=600).split("\n")))
        try:
            xlinfo = kvs2dict("xlinfo:", map2kvs(endpoint.execcmd("xl info").replace(": ","=").split("\n")))
        except Exception, e: #if xl not available, use lscpu for bare metal machines
            xlinfo = {}
            if endpointHost.productType == "esx":
                self.log(None, "using vim-cmd: %s" % (e,))
                cpuinfo = kvs2dict("cpuinfo:", map2kvs(map(lambda x: x.strip(","), endpoint.execcmd("vim-cmd hostsvc/hosthardware | grep -A 6 'cpuInfo = '").replace(" = ","=").split("\n"))))
                # Note: not a 1-to-1 mapping between ESXi's notions and xl info's notions of these things.
                xlinfo["cpuinfo:numCpuPackages"] = cpuinfo["cpuinfo:numCpuPackages"] # number of physical sockets
                xlinfo["cpuinfo:numCpuCores"]    = cpuinfo["cpuinfo:numCpuCores"]
                xlinfo["cpuinfo:numCpuThreads"]  = cpuinfo["cpuinfo:numCpuThreads"]
                xlinfo["cpuinfo:numNumaNodes"]   = "unknown" # I can't find a way of working this out
            else:
                self.log(None, "using lscpu: %s" % (e,))
                lscpu = kvs2dict("lscpu:", map2kvs(endpoint.execcmd("lscpu").replace(": ","=").split("\n")))
                xlinfo["xlinfo:nr_cpus"] = lscpu["lscpu:CPU(s)"]
                xlinfo["xlinfo:cores_per_socket"] = lscpu["lscpu:Core(s) per socket"]
                xlinfo["xlinfo:threads_per_core"] = lscpu["lscpu:Thread(s) per core"]
                xlinfo["xlinfo:nr_nodes"] = lscpu["lscpu:NUMA node(s)"]

        if endpointHost.productType == "esx":
            # We need to extract at least the equivalent info to the "model name" and "cpu MHz"
            cpuinfo = kvs2dict("cpuinfo:", map(lambda x: map(lambda x: x.strip("\", "), x), map2kvs(endpoint.execcmd("vim-cmd hostsvc/hosthardware | grep -A 8 'cpuPkg = '").replace(" = ","=").split("\n"))))
            cpuinfo["cpuinfo:model name"] = cpuinfo["cpuinfo:description"]
            cpuinfo["cpuinfo:cpu MHz"] = int(cpuinfo["cpuinfo:hz"])/1000000
        else:
            cpuinfo = kvs2dict("cpuinfo:", map2kvs(endpoint.execcmd("cat /proc/cpuinfo").replace(": ","=").split("\n")))

        info = {}
        info["nic_physdev"] = dev
        info["nic_desc"] = dev_desc
        info.update(ethtool)
        info.update(ethtool_i)
        info.update(ethtool_k)
        info.update(ethtool_P)
        info.update(ethtool_g)
        info.update(proc_sys_net)
        info.update(sys_class_net)
        info.update(sys_devices)
        info.update(xlinfo)
        info.update(cpuinfo)
        return dict( [ (("%s%s" % (key_prefix, k)), v) for k,v in info.iteritems() ] )

    def getHostname(self, endpoint):
        return endpoint.execcmd("hostname").strip()

    def physicalDeviceOf(self, guest, endpointdev):
        if endpointdev is None:
            return None
        else:
            (_, bridge, _, _) = guest.vifs[endpointdev]
            # TODO is it safe to assume that xenbrN corresponds to XenRT's idea of NIC N?
            if bridge.startswith("xenbr"):
                return int(bridge[5:])

    def getIssue(self, endpoint):
        issue = endpoint.execcmd("head -n 1 /etc/issue || true").strip()
        if issue == "":
            issue = "no-issue"
        return issue

    def rageinfo(self, info = {}):
        if isinstance(self.endpoint0, xenrt.GenericHost):
            info.update(self.nicinfo(self.endpoint0,self.e0dev,"host0:"))
            info["vm0type"]  = "host"
            info["vm0ram"]   = "NULL"
            info["vm0vcpus"] = "NULL"
            info["vm0domid"] = "NULL"
            info["host0product"] = self.endpoint0.productType
            info["host0branch"]  = self.endpoint0.productVersion
            info["host0build"]   = self.endpoint0.productRevision
            info["host0issue"]   = self.getIssue(self.endpoint0)
            info["host0hostname"]= self.getHostname(self.endpoint0)
        elif isinstance(self.endpoint0, xenrt.GenericGuest):
            #info.update(self.nicinfo(self.endpoint0,self.e0dev,"guest0:"))
            info.update(self.nicinfo(self.endpoint0.host,self.physicalDeviceOf(self.endpoint0, self.e0dev),"host0:"))
            info["vm0type"]  = self.endpoint0.distro
            info["vm0ram"]   = self.endpoint0.memory
            info["vm0vcpus"] = self.endpoint0.vcpus
            info["vm0domid"] = self.endpoint0.getDomid()
            info["host0product"] = self.endpoint0.host.productType
            info["host0branch"]  = self.endpoint0.host.productVersion
            info["host0build"]   = self.endpoint0.host.productRevision
            info["host0issue"]   = self.getIssue(self.endpoint0.host)
            info["host0hostname"]= self.getHostname(self.endpoint0.host)
        if isinstance(self.endpoint1, xenrt.GenericHost):
            info.update(self.nicinfo(self.endpoint1,self.e1dev,"host1:"))
            info["vm1type"]  = "host"
            info["vm1ram"]   = "NULL"
            info["vm1vcpus"] = "NULL"
            info["vm1domid"] = "NULL"
            info["host1product"] = self.endpoint1.productType
            info["host1branch"]  = self.endpoint1.productVersion
            info["host1build"]   = self.endpoint1.productRevision
            info["host1issue"]   = self.getIssue(self.endpoint1)
            info["host1hostname"]= self.getHostname(self.endpoint1)
        elif isinstance(self.endpoint1, xenrt.GenericGuest):
            #info.update(self.nicinfo(self.endpoint1,self.e1dev,"guest1:"))
            info.update(self.nicinfo(self.endpoint1.host,self.physicalDeviceOf(self.endpoint1, self.e1dev),"host1:"))
            info["vm1type"]  = self.endpoint1.distro
            info["vm1ram"]   = self.endpoint1.memory
            info["vm1vcpus"] = self.endpoint1.vcpus
            info["vm1domid"] = self.endpoint1.getDomid()
            info["host1product"] = self.endpoint1.host.productType
            info["host1branch"]  = self.endpoint1.host.productVersion
            info["host1build"]   = self.endpoint1.host.productRevision
            info["host1issue"]   = self.getIssue(self.endpoint1.host)
            info["host1hostname"]= self.getHostname(self.endpoint1.host)
        kvs = "\n".join(["%s=%s" % (k,info[k]) for k in info.keys()])
        self.log("rageinfo", kvs)

    def setup_gro(self):
        def setgro(endpoint):
            dev, mac = self.nicdev(endpoint)
            if self.gro in ["on", "off"]:
                endpoint.execcmd("ethtool -K %s gro %s" % (dev, self.gro))
            elif self.gro in ["default", ""]:
	        self.log(None, "not overriding gro option for %s" % (dev,))
            else:
                raise xenrt.XRTError("unknown gro option: %s" % (self.gro,))
        if isinstance(self.endpoint0, xenrt.GenericHost):
            setgro(self.endpoint0)
        elif isinstance(self.endpoint0, xenrt.GenericGuest):
            setgro(self.endpoint0.host)
        if isinstance(self.endpoint1, xenrt.GenericHost):
            setgro(self.endpoint1)
        elif isinstance(self.endpoint1, xenrt.GenericGuest):
            setgro(self.endpoint1.host)

    def vmunpause(self):
        if isinstance(self.endpoint0, xenrt.GenericGuest):
            if self.endpoint0.getState() == "PAUSED": self.endpoint0.unpause()
        if isinstance(self.endpoint1, xenrt.GenericGuest):
            if self.endpoint1.getState() == "PAUSED": self.endpoint1.unpause()
        time.sleep(20)

    def vmpause(self):
        if isinstance(self.endpoint0, xenrt.GenericGuest):
            self.endpoint0.pause()
        if isinstance(self.endpoint1, xenrt.GenericGuest):
            self.endpoint1.pause()

    def breathe(self):
        # try to work out all paused endpoints
        for g in self.guests:
            try:
                g.unpause()
                g.checkReachable()
                g.pause()
            except Exception, e:
                self.log(None, "error while breathing: %s" % (e,))

    def run(self, arglist=None):

        # unpause endpoints if paused
        self.vmunpause()
        # set up gro if required
        self.setup_gro()

        # Install udpgen in both places if necessary
        if 'udpgen_installed' not in self.endpoint0.__dict__.keys():
            self.endpoint0.installUDPGen()
            self.endpoint0.udpgen_installed = True
        if 'udpgen_installed' not in self.endpoint1.__dict__.keys():
            self.endpoint1.installUDPGen()
            self.endpoint1.udpgen_installed = True

        # Give IP addresses to the endpoints if necessary
        if self.e0ip:
            self.setIPAddress(self.endpoint0, self.e0dev, self.e0ip)
        if self.e1ip:
            self.setIPAddress(self.endpoint1, self.e1dev, self.e1ip)

        # Collect as much information as necessary for the rage importer
        self.rageinfo()

        # Run some traffic in one direction
        stdout, stderr = self.runUDPGen(self.endpoint1, self.e1dev, self.endpoint0, self.e0dev, self.npkts, self.size, self.tolerance)
        self.log("udpgen.1to0", stdout.strip())
        self.log("udpgenerr.1to0", stderr.strip())

        # Now run traffic in the reverse direction
        stdout, stderr = self.runUDPGen(self.endpoint0, self.e0dev, self.endpoint1, self.e1dev, self.npkts, self.size, self.tolerance)
        self.log("udpgen.0to1", stdout.strip())
        self.log("udpgenerr.0to1", stderr.strip())

        # pause endpoints again to avoid interfering with measurements on other vms
        self.vmpause()

        # don't let vms in the paused state for too long
        # without network activity: windows vms tend to forget their ips
        self.breathe()

    def postRun(self):
        self.finishUp()
