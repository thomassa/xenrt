import xenrt
from datetime import datetime
from pprint import pformat

class _TCCloudResiliencyBase(xenrt.TestCase):
    def prepare(self, arglist):
        self.cloud = self.getDefaultToolstack()
        self.instances = []
        args = self.parseArgsKeyValue(arglist)
        for zone in self.cloud.marvin.cloudApi.listZones():
            self.instances += self.createInstances(zoneName=zone.name,
                                                   distroList=args.has_key('distros') and args['distros'].split(','))
        map(lambda x:x.assertHealthy(), self.instances)

    def createInstances(self, zoneName, distroList=None, instancesPerDistro=1):
        instances = []
        zoneid = self.cloud.marvin.cloudApi.listZones(name=zoneName)[0].id
        # Use existing templates (if any)
        existingTemplates = self.cloud.marvin.cloudApi.listTemplates(templatefilter='all', zoneid=zoneid)
        templateList = filter(lambda x:x.templatetype != 'SYSTEM' and x.templatetype != 'BUILTIN', existingTemplates)

        if len(templateList) != 0:
            # Use the template names
            templateList = map(lambda x:x.name, templateList)
        else:
            # Create templates based on the distro list
            for distro in distroList:    
                distroName = distro.replace('_','-')
                instance = self.cloud.createInstance(distro=distro, name='%s-template' % (distroName))
                templateName = '%s-tplt' % (distroName)
                self.cloud.createTemplateFromInstance(instance, templateName)
                instance.destroy()
                templateList.append(templateName)

        xenrt.TEC().logverbose('Using templates: %s' % (','.join(templateList)))

        # Create instances
        for templateName in templateList:
            instances += map(lambda x:self.cloud.createInstanceFromTemplate(templateName=templateName, 
                                                                            name='%s-%d' % (templateName.replace("_","-"), x)), range(instancesPerDistro))
        return instances

class TCStorageResiliency(_TCCloudResiliencyBase):
    def logCloudHostInfo(self):
        keysToLog = ['state', 'events', 'lastpinged', 'disconnected', 'created', 'resourcestate']
        hosts = self.cloud.marvin.cloudApi.listHosts(type='Routing')
        for host in hosts:
            if host.hypervisor == 'XenServer':
                try:
                    h = filter(lambda x:x.getName() == host.name, self.getAllHosts())[0]
                    xenrt.TEC().logverbose('[%s] BOOT-TIME: %s' % (host.name, datetime.fromtimestamp(int(float(h.getHostParam("other-config", "boot_time")))).strftime('%d-%m %H:%M')))
                    xenrt.TEC().logverbose('[%s] XAPI-TIME: %s' % (host.name, datetime.fromtimestamp(int(float(h.getHostParam("other-config", "agent_start_time")))).strftime('%d-%m %H:%M')))
                except Exception, e:
                    xenrt.TEC().logverbose('Reg:\n' + pformat(xenrt.TEC().registry.__dict__))
                    xenrt.TEC().logverbose('Could not get data from XS Host [%s]: Exception: %s' % (host.name, str(e)))
            map(lambda x:xenrt.TEC().logverbose('[%s] %20s = %s' % (host.name, x, getattr(host, x))), keysToLog)

    def diffZoneCapacityWithCurrent(self, zoneid, oldCapacityData=[], capacityTypeIdList=None):
        newCapacityData = self.cloud.marvin.cloudApi.listCapacity(zoneid=zoneid)
        capacityDataChanged = False
        for oldCapacity in oldCapacityData:
            newCapacity = filter(lambda x:x.type == oldCapacity.type, newCapacityData)
            xenrt.xrtAssert(len(newCapacity) == 1, 'Inconsistent capacity data reported by MS')
            if oldCapacity.__dict__ != newCapacity[0].__dict__:
                diffLogStr = 'DIFF IGNORED: '
                if capacityTypeIdList == None or oldCapacity.type in capacityTypeIdList:
                    diffLogStr = 'DIFF DETECTED: '
                    capacityDataChanged = True
                xenrt.TEC().logverbose(diffLogStr + 'TYPE: %d: Old capacity: %s, new capacity: %s' % (oldCapacity.type, pformat(oldCapacity), pformat(newCapacity[0])))
        return (capacityDataChanged, newCapacityData)

class TCPrimaryStorageResiliency(TCStorageResiliencyBase):

    def waitForSystemVmAgentState(self, podid, state, timeout=300, pollPeriod=20):
        """Wait for all System VMs (associated with the Pod) to reach the specified state"""
        allSystemVmsReachedState = False
        startTime = datetime.now()
        while (datetime.now() - startTime).seconds < timeout:
            systemVmData = self.cloud.marvin.cloudApi.listSystemVms(podid=podid)
            systemVmNameList = map(lambda x:x.name, systemVmData)
            hostData = filter(lambda x:x.name in systemVmNameList, self.cloud.marvin.cloudApi.listHosts())
            self.logCloudHostInfo()
            if len(systemVmData) != len(hostData):
                xenrt.TEC().warning('Inconsistent System VM and Host data reported by MS')
#            xenrt.xrtAssert(len(systemVmData) == len(hostData), 'Inconsistent System VM and Host data reported by MS')
            xenrt.TEC().logverbose('System VM State: %s' % (pformat(map(lambda x:(x.name, x.state), systemVmData))))
            systemVmsNotInState = filter(lambda x:x.state != state, hostData)
            if len(systemVmsNotInState) == 0:
                if state == 'Up':
                    # Check that the system VMs are also all Running
                    systemVmsUpButNotInRunningState = filter(lambda x:x.state != 'Running', systemVmData)
                    if len(systemVmsUpButNotInRunningState) > 0:
                        xenrt.TEC().warning('System VM(s) %s reported as Up but not Running' % (pformat(map(lambda x:(x.name, x.state), systemVmsUpButNotInRunningState))))
                        continue

                xenrt.TEC().logverbose('System VMs [%s] reached state: %s in %d sec' % (systemVmNameList, state, (datetime.now() - startTime).seconds))
                allSystemVmsReachedState = True
                break
            else:
                xenrt.TEC().logverbose('Waiting for the following system VMs to reach state %s: %s' % (state, pformat(map(lambda x:(x.name, x.state), systemVmsNotInState))))
                xenrt.sleep(pollPeriod)

        self.logCloudHostInfo()
        if not allSystemVmsReachedState:
            raise xenrt.XRTFailure('Not all System VMs reached state %s in %d seconds' % (state, timeout))

    def waitForHostState(self, podid, state, timeout=300, pollPeriod=20):
        """Wait for all Hosts (associated with the Pod) to reach the specified state"""
        allHostsReachedState = False
        startTime = datetime.now()
        while (datetime.now() - startTime).seconds < timeout:
            hostData = self.cloud.marvin.cloudApi.listHosts(type='Routing', podid=podid)
            hostsNotInState = filter(lambda x:x.state != state, hostData)
            if len(hostsNotInState) == 0:
                allHostsReachedState = True
                break
            else:
                xenrt.TEC().logverbose('Waiting for the following Hosts to reach state %s: %s' % (state, pformat(map(lambda x:(x.name, x.state), hostsNotInState))))
                self.logCloudHostInfo()
                xenrt.sleep(pollPeriod)

        self.logCloudHostInfo()
        if not allHostsReachedState:
            raise xenrt.XRTFailure('Not all Hosts reached state %s in %d seconds' % (state, timeout))

    def waitForUserInstanceState(instanceNames, state, timeout=300):
        """Wait for all User Instances (specified) to reach the specified state"""
        allInstancesReachedState = False
        startTime = datetime.now()
        while (datetime.now() - startTime).seconds < timeout:
            instanceData = filter(lambda x:x.name in instanceNames, self.cloud.marvin.cloudApi.listVirtualMachines())
            xenrt.xrtAssert(len(instanceNames) == len(instanceData), 'Did not find instance records for all specified isntance names')   

            instancesNotInState = filter(lambda x:x.state != state, instanceData)
            if len(instancesNotInState) == 0:
                allInstancesReachedState = True
                break
            else:
                xenrt.TEC().logverbose('Waiting for the following User Instances to reach state %s: %s' % (state, pformat(map(lambda x:(x.name, x.state), instancesNotInState))))
                xenrt.sleep(pollPeriod)

        if not allInstancesReachedState:
            raise xenrt.XRTFailure('Not all User Instances reached state %s in %d seconds' % (state, timeout))

class TC99999901(TCPrimaryStorageResiliency):
    """Primary Storage Resiliency for System VMs"""
    VERIFY_USER_INSTANCES = False

    def prepare(self, arglist):
        self.cloud = self.getDefaultToolstack()
        self.instances = []

        zones = self.cloud.marvin.cloudApi.listZones()
        xenrt.xrtAssert(len(zones) == 1, 'There must be 1 and only 1 zone configured for this test-case')
        self.zoneid = zones[0].zoneid

        pods = self.cloud.marvin.cloudApi.listPods()
        xenrt.xrtAssert(len(pods) == 1, 'There must be 1 and only 1 pod configured for this test-case')
        self.podid = pods[0].id
     
        if self.VERIFY_USER_INSTANCES:
            self.instances = self.createInstances(zoneName=zones[0].name,
                                                  distroList=['centos59_x86-32', 'win7sp1-x86'],
                                                  instancesPerDistro=1)
            map(lambda x:x.assertHealthy(), self.instances)

        # Check all System VMs are ok before the test is run
        self.waitForSystemVmAgentState(self.podid, state='Up', timeout=60)

        args = self.parseArgsKeyValue(arglist)
        storageVMName = args.has_key('storageVM') and args['storageVM'] or None
        self.storageVM = xenrt.TEC().registry.guestGet(storageVMName)
        self.storageVM.checkHealth()

    def verifySystemVMsRecoverFromOutage(self):
        systemVms = self.cloud.marvin.cloudApi.listSystemVms(podid=self.podid)
        cpvms = filter(lambda x:x.systemvmtype == 'consoleproxy', systemVms)
        ssvms = filter(lambda x:x.systemvmtype == 'secondarystoragevm', systemVms)
        xenrt.xrtAssert(len(cpvms) + len(ssvms) == len(systemVms), 'Unexpected System VM type reported')

        (ignore, originalCapacity) = self.diffZoneCapacityWithCurrent(zoneid=self.zoneid)

        # Stop the storage VM (simulate the outage)
        self.storageVM.shutdown(force=True)
        # Wait for the system VMs to reach the disconnected state
        self.waitForSystemVmAgentState(self.podid, state='Disconnected', timeout=600)
        
        self.storageVM.start()
        # Wait for the system VMs to recover
        self.waitForSystemVmAgentState(self.podid, state='Up', timeout=1200)

        # Check the number of system VMs has not changed
        newsystemVms = self.cloud.marvin.cloudApi.listSystemVms(podid=self.podid)
        newcpvms = filter(lambda x:x.systemvmtype == 'consoleproxy', newsystemVms)
        newssvms = filter(lambda x:x.systemvmtype == 'secondarystoragevm', newsystemVms)
        xenrt.xrtAssert(len(newcpvms) + len(newssvms) == len(newsystemVms), 'Unexpected System VM type reported')
        xenrt.xrtAssert(len(cpvms) == len(newcpvms), 'Number of Console Proxy VMs not the same after outage')
        xenrt.xrtAssert(len(ssvms) == len(newssvms), 'Number of Secondary Storage VMs not the same after outage')

        # Chkec all Hosts are Up and then recheck that all System VMs are still up
        self.waitForHostState(self.podid, state='Up', timeout=600)
        self.waitForSystemVmAgentState(self.podid, state='Up', timeout=300)

        if self.VERIFY_USER_INSTANCES:
            self.waitForUserInstanceState(instanceNames=map(lambda x:x.name, self.instances), state='Running', timeout=300)

            for instance in self.instances:
                try:
                    instance.assertHealthy()
                except Exception, e:
                    # VMs may fail when their disks are removed - reboot any VMs that are not responding
                    xenrt.TEC().logverbose('Instance: %s health check failed with: %s' % (instance.name, str(e)))
                    xenrt.TEC().logverbose('Reboot instance: %s' % (instance.name))
                    instance.reboot()

            self.waitForUserInstanceState(instanceNames=map(lambda x:x.name, self.instances), state='Running', timeout=300)
            map(lambda x:x.assertHealthy(), self.instances)

            # Verify that all VRs are running
            nonRunningVRs = filter(lambda x:x.state != 'Running', self.cloud.marvin.cloudApi.listRouters(listall='true'))
            if len(nonRunningVRs) > 0:
                xenrt.TEC().logverbose('VRs not in Running state: %s' % (pformat(map(lambda x:(x.name, x.state), nonRunningVRs))))
                raise xenrt.XRTFailure('VR(s) not recovered after Primary Storage Outage')

        (ignore, originalCapacity) = self.diffZoneCapacityWithCurrent(zoneid=self.zoneid, oldCapacityData=originalCapacity)
        # TODO - Run CCP health check

    def run(self, arglist):
        hosts = self.cloud.marvin.cloudApi.listHosts(type='Routing')
        for host in hosts:
            # Move all system VMs and routers to this host
            systemVMsNotOnThisHost = filter(lambda x:x.hostname != host.name, self.cloud.marvin.cloudApi.listSystemVms())
            xenrt.TEC().logverbose('Migrating System VMs %s to host: %s' % (map(lambda x:x.name, systemVMsNotOnThisHost), host.name))
            map(lambda x:self.cloud.marvin.cloudApi.migrateSystemVm(hostid=host.id, virtualmachineid=x.id), systemVMsNotOnThisHost)
            self.waitForSystemVmAgentState(self.podid, state='Up', timeout=60)

            # Move all instances to this host
            instancesNotOnThisHost = filter(lambda x:x.residentOn != host.name, self.instances)
            xenrt.TEC().logverbose('Migrating insstances %s to hosts: %s' % (map(lambda x:x.name, instancesNotOnThisHost), host.name))
            map(lambda x:x.migrate(to=host.name), instancesNotOnThisHost)
            self.waitForUserInstanceState(instanceNames=map(lambda x:x.name, self.instances), state='Running', timeout=300)

            self.runSubcase('verifySystemVMsRecoverFromOutage', (), 'SysVMPriStoreResiliency', 'Host=%s' % (host.name))

class TC99999902(TC99999901):
    """Primary Storage Resiliency for User Instances"""
    VERIFY_USER_INSTANCES = True

class _TCManServerResiliencyBase(_TCCloudResiliencyBase):

    def recover(self):
        pass

    def specificCheck(self):
        pass

    def genericCheck(self):
        map(lambda x:x.assertHealthy(), self.instances)
        # TODO - Check CCP health

    def run(self, arglist):
        self.args = self.parseArgsKeyValue(arglist)
        iterations = self.args.has_key('iterations') and self.args['iterations'] or 3

        for i in range(iterations):
            self.runSubcase('outage', (), 'Outage', 'Iter-%d' % (i))
            self.runSubcase('recover', (), 'Recover', 'Iter-%d' % (i))
            self.runSubcase('specificCheck', (), 'SpecificCheck', 'Iter-%d' % (i))
            self.runSubcase('genericCheck', (), 'GenericCheck', 'Iter-%d' % (i))

    def waitForCCP(self):
        deadline = xenrt.timenow() + 600
        while True:
            try:
                self.cloud.cloudApi.listHosts()
                break
            except:
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTFailure("Cloudstack Management did not come back after 10 minutes")
                xenrt.sleep(15) 

    def postRun(self):
        # See if the management server is behaving, if not, restart it
        try:
            self.cloud.cloudApi.listHosts()
        except:
            self.cloud.mgtsvr.restart()

class TCManServerVMReboot(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        msvm.reboot()

    def recover(self):
        self.waitForCCP()


class TCManServerRestart(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        msvm.execcmd("service cloudstack-management restart")

    def recover(self):
        self.waitForCCP()


class TCDBRestart(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        msvm.execcmd("service mysqld restart")

    def recover(self):
        self.waitForCCP()


class TCDBOutage(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        msvm.execcmd("service mysqld stop")
        xenrt.sleep(120)
        msvm.execcmd("service mysqld start")

    def recover(self):
        self.waitForCCP()

class TCManServerStartAfterDB(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        msvm.execcmd("service mysqld stop")
        msvm.execcmd("service cloudstack-management stop")
        
        msvm.execcmd("service cloudstack-management start")
        
        xenrt.sleep(120)

        msvm.execcmd("service mysqld start")

    def recover(self):
        self.waitForCCP()
