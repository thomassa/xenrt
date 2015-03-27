from abc import ABCMeta, abstractproperty, abstractmethod
from xenrt.enum import XenServerLicenseSKU
import re
import xenrt

__all__ = ["WorkloadBalancing", "ReadCaching",
           "VirtualGPU", "Hotfixing", "ExportPoolResourceList",
           "GPUPassthrough", "LicensedFeatureFactory"]


class LicensedFeature(object):

    """
    Class to check the licensing and actual state of a sepcific feature
    """
    __metaclass__ = ABCMeta

    @abstractproperty
    def name(self):
        pass

    @abstractmethod
    def isEnabled(self, host):
        """
        Is the feature programmatically enabled on the server side
        @rtype boolean list
        """
        pass

    @abstractproperty
    def featureFlagName(self):
        """
        What is the name of the feature flag
        @rtype string
        """
        pass

    def hostFeatureFlagValue(self, host, nolog=False):
        """
        What is the value of the host's feature flag
        @rtype boolean
        """
        cli = host.getCLIInstance()
        data = cli.execute("host-license-view",
                           "host-uuid=%s" % (host.getMyHostUUID()), nolog=nolog)
        return self._searchForFlag(data, self.featureFlagName)

    def _searchForFlag(self, data, flag):
        """ Regex here matches:
            "my_flag": "my_data" <-TapCtl Formatted JSON
            my_flag: my_data <- xapi formatted
            and mixtures of the two
        """
        regex = """[\"]*%s[\"]*: (?P<flagValue>[\w\"]+)""" % flag
        match = re.search(regex, data)
        if match:
            return match.group("flagValue").strip().replace('\"', '') == "true"
        return False

    def poolFeatureFlagValue(self, pool):
        """
        What is the value of the host's feature flag
        @rtype boolean
        """
        poolParams = pool.getPoolParam("restrictions")
        return self._searchForFlag(poolParams, self.featureFlagName)

    @property
    def stateCanBeChecked(self):
        """
        Can the enabled state be checked? Maybe false is this
        is a flagged UI feature
        @rtype boolean
        """
        return True


class WorkloadBalancing(LicensedFeature):

    @property
    def name(self):
        return "WorkloadBalancing"

    def isEnabled(self, host):
        raise NotImplementedError()

    @property
    def featureFlagName(self):
        return "restrict_wlb"

    @property
    def stateCanBeChecked(self):
        return False


class ReadCaching(LicensedFeature):

    __TAP_CTRL_FLAG = "read_caching"

    @property
    def name(self):
        return "ReadCaching"

    def __fetchPidAndMinor(self, host):
        regex = re.compile("""{0}=(\w+) {1}=(\w+)""".format("pid", "minor"))
        data = host.execdom0("tap-ctl list | cat")
        return regex.findall(data)

    def isEnabled(self, host):
        pidAndMinors = self.__fetchPidAndMinor(host)
        output = []
        for pid, minor in pidAndMinors:
            readCacheDump = host.execdom0("tap-ctl stats -p %s -m %s" % (pid, minor))
            output.append(self._searchForFlag(readCacheDump, self.__TAP_CTRL_FLAG))
        return output

    @property
    def featureFlagName(self):
        return "restrict_read_caching"


class VirtualGPU(LicensedFeature):

    @property
    def name(self):
        return "VirtualGPU"

    def isEnabled(self, host):
        """Try to start every vm on the host with a GPU attached."""

        def tryStartVM(vm):
            try:
                vm.setState("UP")
                return True
            except:
                return False

        vms = [vm for vm in host.guests.values() if vm.hasvGPU()]

        if not vms:
            raise xenrt.XRTError("There are no VMs present with a GPU attached.")

        [vm.setState("DOWN") for vm in vms]

        return next((True for vm in vms if vm.tryStartVM()), False)

    @property
    def featureFlagName(self):
        return "restrict_vgpu"


class GPUPassthrough(VirtualGPU):

    @property
    def name(self):
        return "GPUPassthrough"

    @property
    def featureFlagName(self):
        return "restrict_gpu"


class Hotfixing(LicensedFeature):

    @property
    def name(self):
        return "Hotfixing"

    def isEnabled(self, host):
        raise NotImplementedError()

    @property
    def featureFlagName(self):
        return "restrict_hotfix_apply"

    @property
    def stateCanBeChecked(self):
        return False


class ExportPoolResourceList(LicensedFeature):

    @property
    def name(self):
        return "ExportPoolResourceList"

    def isEnabled(self, host):
        raise NotImplementedError()

    @property
    def featureFlagName(self):
        return "restrict_export_resource_data"

    @property
    def stateCanBeChecked(self):
        return False

class CreedenceEnabledFeatures(object):

    def __init__(self,sku):
        self.sku = sku

    def getEnabledFeatures(self):
        if self.sku == XenServerLicenseSKU.PerUserEnterprise or \
           self.sku == XenServerLicenseSKU.PerConcurrentUserEnterprise:
            return [WorkloadBalancing().name,ReadCaching().name,VirtualGPU().name,
                    Hotfixing().name, ExportPoolResourceList().name, GPUPassthrough().name]
        if self.sku == XenServerLicenseSKU.PerSocketEnterprise or \
           self.sku == XenServerLicenseSKU.PerSocket:
            return [WorkloadBalancing().name,ReadCaching().name,VirtualGPU().name,
                    Hotfixing().name, ExportPoolResourceList().name, GPUPassthrough().name]
        if self.sku == XenServerLicenseSKU.XenDesktop:
            return [Hotfixing().name, GPUPassthrough().name,WorkloadBalancing().name,VirtualGPU().name]
        if self.sku == XenServerLicenseSKU.PerSocketStandard:
            return [Hotfixing().name, GPUPassthrough().name]
        if self.sku == XenServerLicenseSKU.Free:
            return [Hotfixing().name, GPUPassthrough().name] 
        if self.sku == XenServerLicenseSKU.XenDesktopPlusXDS or \
           self.sku == XenServerLicenseSKU.XenDesktopPlusMPS:
            return [WorkloadBalancing().name,ReadCaching().name,VirtualGPU().name,
                    Hotfixing().name, GPUPassthrough().name]

    def expectedEnabledState(self, feature):

        if feature.name in self.getEnabledFeatures():
            return False
        else:
            return True

class LicensedFeatureFactory(object):
    __CRE = "creedence"
    __CRM = "cream"
    __DUN = "dundee"

    def __getHostAge(self, xshost):
        return xshost.productVersion.lower()

    def __createDictOfFeatures(self, *featureList):
        return dict([(f.name, f) for f in featureList])

    def allFeatures(self, xshost):
        if self.__getHostAge(xshost) == self.__CRE or self.__getHostAge(xshost) == self.__CRM or self.__getHostAge(xshost) == self.__DUN:
            return  self.__createDictOfFeatures(WorkloadBalancing(), ReadCaching(), VirtualGPU(),
                                                Hotfixing(), ExportPoolResourceList(), GPUPassthrough())
        raise ValueError("Feature list for a %s host was not found" % self.__getHostAge(xshost))

    def allFeatureObj(self,xshost):
        if self.__getHostAge(xshost) == self.__CRE or self.__getHostAge(xshost) == self.__DUN or self.__getHostAge(xshost) == self.__CRM:
            return [WorkloadBalancing(), ReadCaching(), VirtualGPU(),
                                                Hotfixing(), ExportPoolResourceList(), GPUPassthrough()]
 
    def getFeatureState(self, productVersion, sku, feature):
        lver = productVersion.lower()
        if lver == self.__CRE or lver == self.__CRM or lver == self.__DUN:
            return CreedenceEnabledFeatures(sku).expectedEnabledState(feature)
