
import xenrt
import os
import re
import IPy
from pprint import pformat
from xenrt.lazylog import *

__all__ = ["NetScaler"]

class NetScaler(object):
    """Class that provides an interface for creating, controlling and observing a NetScaler VPX"""

    @classmethod
    def setupNetScalerVpx(cls, vpx, useExistingVIFs=False, networks=["NPRI"], license=None):
        """Takes a VM name (present in the registry) and returns a NetScaler object"""
        if isinstance(vpx, basestring):
            vpxGuest = xenrt.TEC().registry.guestGet(vpx)
        else:
            vpxGuest = vpx
        host = vpxGuest.host
        xenrt.TEC().logverbose('Using VPX Appliance: %s on host: %s - current state: %s' % (vpxGuest.getName(), host.getName(), vpxGuest.getState()))
        xenrt.TEC().logverbose("VPX Guest:\n" + pformat(vpxGuest.__dict__))
        vpxGuest.noguestagent = True
        vpxGuest.password = 'nsroot'
        _removeHostFromVCenter = False
        if isinstance(host, xenrt.lib.esx.ESXHost) and not host.datacenter:
            _removeHostFromVCenter = True
            host.addToVCenter()

        vpxMgmtIp = cls.getVpxIpFromVmParams(vpxGuest)
        if vpxMgmtIp and vpxGuest.mainip and vpxMgmtIp==vpxGuest.mainip:
            if vpxGuest.getState() == 'DOWN':
                vpxGuest.lifecycleOperation('vm-start')
            # Wait / Check for SSH connectivity
            vpxGuest.waitForSSH(timeout=300, username='nsroot', cmd='shell')
            vpx = cls(vpxGuest, None)
        else:
            warning('Netscaler VPX guest has inconsistent or NULL IP Address')
            if vpxGuest.getState() == 'UP':
                vpxGuest.shutdown()

            if not useExistingVIFs:
                # Configure the VIFs
                vpxGuest.removeAllVIFs()
                for n in networks:
                    # createVIF() method still lacks support for NSEC on non-xenserver hypervisors
                    vpxGuest.createVIF(bridge=n)
            else:
                networks = [host.getNICNetworkName(host.getAssumedId(x[1])) for x in vpxGuest.vifs]

            networks_sriov = [x[1] for x in vpxGuest.sriovvifs]

            mgmtNet = networks[0]
            cls.configureVpxNetworkToVmParams(vpxGuest, mgmtNet)
            vpxGuest.lifecycleOperation('vm-start')

            # Wait / Check for SSH connectivity
            vpxGuest.waitForSSH(timeout=300, username='nsroot', cmd='shell')
            vpx = cls(vpxGuest, mgmtNet)
            vpx.checkFeatures("On fresh install:")

            # Apply license
            if license:
                vpx.applyLicense(license)
                vpx.checkFeatures("Test results after applying license:")

            # Setup networking
            vpx.setup(networks, networks_sriov)
        if _removeHostFromVCenter:
            host.removeFromVCenter()
        return vpx

    @classmethod
    def configureVpxNetworkToVmParams(cls, vpxGuest, mgmtNet):
        """Configure the management network for the VPX"""
        vpxGuest.mainip = xenrt.StaticIP4Addr(network=mgmtNet).getAddr()
        gateway = xenrt.getNetworkParam(mgmtNet, "GATEWAY")
        mask = xenrt.getNetworkParam(mgmtNet, "SUBNETMASK")
        if isinstance(vpxGuest, xenrt.lib.xenserver.Guest):
            vpxGuest.paramSet('xenstore-data:vm-data/ip', vpxGuest.mainip)
            vpxGuest.paramSet('xenstore-data:vm-data/netmask', mask)
            vpxGuest.paramSet('xenstore-data:vm-data/gateway', gateway)
        elif isinstance(vpxGuest, xenrt.lib.esx.Guest):
            paramValue ="ip=%s&netmask=%s&gateway=%s" % (vpxGuest.mainip, mask, gateway)
            vpxGuest.paramSet('machine.id', paramValue)
        else:
            raise xenrt.XRTError("Unimplemented")

    @classmethod
    def getVpxIpFromVmParams(cls, vpxGuest):
        if isinstance(vpxGuest, xenrt.lib.xenserver.Guest):
            try:
                return vpxGuest.paramGet(paramName='xenstore-data', paramKey='vm-data/ip')
            except:
                return None
        elif isinstance(vpxGuest, xenrt.lib.esx.Guest):
            data = vpxGuest.paramGet(paramName='machine.id')
            return data.split("&")[0].strip("ip=") if data else None
        else:
            raise xenrt.XRTError("Unimplemented")

    @classmethod
    def createVPXOnHost(cls, host, vpxName=None, vpxHttpLocation=None):
        """Import a Netscaler VPX onto the specified host"""
        if not vpxName:
            vpxName = xenrt.randomGuestName()
        if not vpxHttpLocation:
            vpxHttpLocation = os.path.join(xenrt.TEC().lookup('EXPORT_DISTFILES_HTTP'), 'tallahassee/NSVPX-XEN-10.0-72.5_nc.xva')
        xenrt.TEC().logverbose('Importing VPX [%s] from: %s to host: %s' % (vpxName, vpxHttpLocation, host.getName()))
        xenrt.productLib(hostname=host.getName()).guest.createVMFromFile(host=host, guestname=vpxName, filename=vpxHttpLocation)
        return cls.setupNetScalerVpx(vpxName)

    def __init__(self, vpxGuest, mgmtNet):
        self.__vpxGuest = vpxGuest
        self.__version = None
        self.__managementIp = None
        self.__subnetips = {}
        self.__mgmtNet = mgmtNet
        xenrt.TEC().logverbose('NetScaler VPX Version: %s' % (self.version))

    def setup(self, networks, networks_sriov):
        i = 1
        ipSpec = self.__vpxGuest.getIPSpec()
        for n in networks[1:]:
            i += 1
            xenrt.TEC().logverbose("Creating VLAN %d for network %s" % (i, n))

            # Find out the name NetScaler has given to the interface
            lines = self.cli("show interfaces")
            iface = next(line.split('\t')[1].split(' ')[1] for line in lines if line.startswith("%d)" % (i)))

            self.cli("add vlan %d" % i)
            self.cli("bind vlan %d -ifnum %s" % (i, iface))
            dev, ip, masklen = [x for x in ipSpec if x[0] == "eth%d" % (i-1)][0]
            if ip:
                self.__subnetips[n] = ip
                subnet = IPy.IP("0.0.0.0/%s" % masklen).netmask().strNormal()
            else:
                try:
                    subnet = xenrt.getNetworkParam(n, "SUBNETMASK")
                except:
                    # Must be a private VLAN with no static IP defined
                    continue
                self.__subnetips[n] = xenrt.StaticIP4Addr(network=n).getAddr()
            self.cli('add ip %s %s' % (self.__subnetips[n], subnet))
            self.cli('bind vlan %d -IPAddress %s %s' % (i, self.__subnetips[n], subnet))
        self.__subnetips[networks[0]] = xenrt.StaticIP4Addr(network=networks[0]).getAddr()
        self.cli('add ip %s %s' % (self.__subnetips[networks[0]], xenrt.getNetworkParam(networks[0], "SUBNETMASK")))

        for n in networks_sriov:
            i += 1
            xenrt.TEC().logverbose("Creating VLAN %d for SR-IOV VIF on network %s" % (i, n))

            # Find out the name NetScaler has given to the interface
            lines = self.cli("show interfaces")
            iface = next(line.split('\t')[1].split(' ')[1] for line in lines if line.startswith("%d)" % (i)))

            # If this network is a VLAN, get the physical VLAN id
            (vlan_id, subnet, netmask) = self.__vpxGuest.host.getVLAN(n) # TODO If it's not a VLAN, just do something like the above
            xenrt.TEC().logverbose("We want a tagged VLAN with id %d" % (vlan_id))

            # Tag traffic on this interface with the VLAN tag
            self.cli("set interface %s -tagall OFF" % (iface))
            self.cli("add vlan %d" % (vlan_id))
            self.cli("bind vlan %d -ifnum %s" % (vlan_id, iface))
            self.cli("set interface %s -tagall ON" % (iface)) # This is necessary to make it work, and it must be done after the 'bind vlan' command.

        self.cli('save ns config')

    def cli(self, command, level=xenrt.RC_FAIL):
        """Helper method for creating specific NetScaler CLI command methods"""
        xenrt.xrtAssert(self.__vpxGuest.getState() == 'UP', 'NetScaler CLI Commands can only be executed on a running VPX')
        data = self.__vpxGuest.execguest(command, username='nsroot', password='nsroot', level=level)
        if type(data) == type(1):
            return
        data = map(lambda x:x.strip(), filter(lambda x:not x.startswith(' Done'), data.splitlines()))
        xenrt.TEC().logverbose('NetScaler Command [%s] - Returned: %s' % (command, '\n'.join(data)))
        return data

    def multiCli(self, cmds):
        [self.cli(cmd.strip()) for cmd in cmds.strip().split("\n") if cmd.strip()]

    def removeExistingSNIP(self):
        snipLines = self.cli("show ns ip | grep SNIP")
        for ip in re.findall( r'[0-9]+(?:\.[0-9]+){3}', "".join(snipLines)):
            self.cli("rm ns ip %s" % (ip))

    def extractTarToDir(self, sourceTarFile, destDir, username="nsroot"):
        tarFile = "/nsconfig/temp.tar.gz"
        self.getGuest().sftpClient(username=username).copyTo(xenrt.TEC().getFile(sourceTarFile),tarFile)
        self.cli("shell tar -xvf %s -C %s" % (tarFile,destDir))

    def installNSTools(self):
        nstools = xenrt.TEC().lookup('NS_TOOLS_PATH')
        toolsfile = nstools.split("/")[-1]
        self.cli("shell mkdir -p /var/BW")
        self.__vpxGuest.sftpClient(username='nsroot').copyTo( xenrt.TEC().getFile(nstools),"/var/BW/%s" % (toolsfile))
        self.cli("shell cd /var/BW && tar xvfz %s" % toolsfile)
        self.cli("shell /var/BW/nscsconfig --help || true")

    @property
    def version(self):
        if not self.__version:
            self.__version = self.cli('show ns version')
        return self.__version

    def reboot(self):
        xenrt.xrtAssert(self.__vpxGuest.getState() == 'UP', 'NetScaler VPX reboot can only be done on a running VPX')
        self.__vpxGuest.lifecycleOperation('vm-reboot')
        # Wait / Check for SSH connectivity
        self.__vpxGuest.waitForSSH(timeout=300, username='nsroot', cmd='shell')
        # On ESX host VM comes up and goes down for around a minute
        if isinstance(self.__vpxGuest, xenrt.lib.esx.Guest):
            xenrt.sleep(60)
            self.__vpxGuest.waitForSSH(timeout=120, username='nsroot', cmd='shell')

    @classmethod
    def getLicenseFileFromXenRT(self):
        # TODO - Allow for different licenses to be specified
        vpxLicneseFileName = 'CNS_V3000_SERVER_PLT_Retail.lic'

        v6dir = xenrt.TEC().tempDir()
        xenrt.util.command('tar -xvzf %s/v6.tgz -C %s v6/conf' % (xenrt.TEC().lookup('TEST_TARBALL_ROOT'), v6dir))
        with open(os.path.join(v6dir, 'v6/conf')) as fh:
            p = fh.read()
        zipfile = "%s/keys/citrix/v6.zip" % (xenrt.TEC().lookup("XENRT_CONF"))
        xenrt.util.command('unzip -P %s -d %s %s %s' % (p, v6dir, zipfile, vpxLicneseFileName))
        licenseFilePath = os.path.join(v6dir, vpxLicneseFileName)
        if not os.path.exists(licenseFilePath):
            raise xenrt.XRTError('Failed to find VPX License')
        xenrt.TEC().logverbose('Using VPX license file: %s' % (licenseFilePath))
        return licenseFilePath

    def applyLicense(self, localLicensePath):
        """Apply the license file specified and apply the license"""
        xenrt.xrtAssert(self.__vpxGuest.getState() == 'UP', 'NetScaler license can only be applied on a running VPX')
        sftp = self.__vpxGuest.sftpClient(username='nsroot')
        sftp.copyTo(localLicensePath, os.path.join('/nsconfig/license', os.path.basename(localLicensePath)))
        sftp.close()
        self.reboot()

        xenrt.xrtAssert(self.isLicensed, 'NetScaler reports being licensed after license file is applied')

    @property
    def isLicensed(self, feature=None):
        if not feature:
            # Use LB as default
            feature = 'Load Balancing'
        licData = filter(lambda x:x.startswith(feature), self.cli('show ns license'))
        xenrt.xrtAssert(len(licData) == 1, 'There is an entry for the specified feature in the NS license data')
        licensed = licData[0].split(':')[1].strip() == 'YES'
        xenrt.TEC().logverbose('NetScaler feature: %s license state = %s' % (feature, licensed))
        return licensed

    @property
    def managementIp(self):
        if not self.__managementIp:
            mgmtIpData = filter(lambda x:'NetScaler IP' in x, self.cli('show ns ip'))
            xenrt.xrtAssert(len(mgmtIpData) == 1, 'The NetScaler only has one management interface defined')
            managementIp = re.search('(\d{1,3}\.){3}\d{1,3}', mgmtIpData[0]).group(0)
            xenrt.xrtAssert(managementIp == self.__vpxGuest.mainip, 'The IP address of the guest matches the reported Netscaler management IP address')
            self.__managementIp = managementIp
        return self.__managementIp

    def subnetIp(self, network=None):
        if not network:
            network="NPRI"
        return self.__subnetips[network]

    def disableL3(self):
        self.cli("disable ns mode L3")
        self.cli('save ns config')

    def setupOutboundNAT(self, privateNetwork, publicNetwork):
        self.cli("set rnat %s %s -natIP %s" % (
                    xenrt.getNetworkParam(privateNetwork, "SUBNET"),
                    xenrt.getNetworkParam(privateNetwork, "SUBNETMASK"),
                    self.subnetIp(network=publicNetwork)))
        self.cli('save ns config')

    def checkModNum(self):
        #returns the model number
        modData = filter(lambda x:x.startswith('Model Number ID'), self.cli('show ns license'))
        modNum = modData[0].split(':')[1].strip()
        return modNum

    def checkCPU(self):
        #writes the number of PEs to log file
        pe = max(map(lambda x: x.split()[0],filter(lambda x: re.match('^\d',x),self.cli('stat cpus'))))
        return pe
        
    def licenseTest(self):
        #checks features before before applying license
        featNo = filter(lambda x: len(x.split(':')) > 1 and x.split(':')[1].strip()=="YES",self.cli('show ns license'))
        if len(featNo) != 1 or featNo[0].split(':')[0].strip()=="SSL offloading":
            xenrt.TEC().logverbose('License test failed')
        else:
            xenrt.TEC().logverbose('License test passed')

    def getGuest(self):
        return self.__vpxGuest

    def checkFeatures(self, msg):
        xenrt.TEC().logverbose(msg)
        xenrt.TEC().logverbose('The version of the provisioned VPX is %s' % (self.version))
        xenrt.TEC().logverbose('The management IP of the provisioned VPX is %s' % (self.managementIp))
        xenrt.TEC().logverbose('The model number ID of the provisioned VPX is %s' % (self.checkModNum()))
        xenrt.TEC().logverbose('The Number of PEs of the provisioned VPX: %s' % (self.checkCPU()))
        xenrt.TEC().logverbose('The build version in ns.conf is: %s' % (self.cli("shell head -1 /flash/nsconfig/ns.conf")))
        xenrt.TEC().logverbose('The show run output in ns.conf is : %s ' % (self.cli('sh run')[0]))
        self.licenseTest()
