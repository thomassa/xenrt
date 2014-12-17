from server import Page
import app.db
import config
import time

class XenRTPage(Page):
    WRITE = False
    DB_SYNC_CHECK_INTERVAL = 0.1

    def __init__(self, request):
        super(XenRTPage, self).__init__(request)
        self._db = None

    def renderWrapper(self):
        try:
            ret = self.render()
            return ret
        finally:
            try:
                if self.WRITE:
                    self.waitForLocalWrite()
            finally:
                if self._db:
                    self._db.rollback()
                    self._db.close()

    def getWriteLocation(self, db):
        cur = db.cursor()
        # Get the current write xlog location from the master
        cur.execute("SELECT pg_current_xlog_location()")
        locStr = cur.fetchone()[0]
        loc = app.utils.XLogLocation(locStr)
        cur.close()
        return loc

    def getReadLocation(self, db):
        cur = db.cursor() 
        cur.execute("SELECT pg_last_xlog_replay_location();")
        locStr = cur.fetchone()[0]
        if locStr:
            loc = app.utils.XLogLocation(locStr)
        else:
            loc = None
        cur.close()
        return loc

    def waitForLocalWrite(self):
        assert self.WRITE
        writeDb = self.getDB()
        writeDb.rollback()
        writeLoc = self.getWriteLocation(writeDb)
        readDb = app.db.dbReadInstance()
        i = 0
        while i < (int(config.db_sync_timeout)/self.DB_SYNC_CHECK_INTERVAL):
            # Get the current xlog replay location from the local DB. This returns none if the local DB is the master
            readLoc = self.getReadLocation(readDb)
            if not readLoc:
                print "Local database is master, don't need to wait for sync"
                # This means the local database is the master, so we can stop
                break
            print "Checking whether writes have synced, attempt %d - write=%s, read=%s" % (i, str(writeLoc), str(readLoc))
            if readLoc >= writeLoc:
                break
            i += 1
            time.sleep(self.DB_SYNC_CHECK_INTERVAL)
        readDb.rollback()
        readDb.close()

    def getDB(self):
        if not self._db:
            if self.WRITE:
                self._db = app.db.dbWriteInstance()
            else:
                self._db = app.db.dbReadInstance()
        return self._db

    def lookup_jobid(self, detailid):
        reply = -1
        cur = self.getDB().cursor()

        cur.execute("SELECT jobid from tblResults WHERE detailid = %s", 
                    [int(detailid)])

        rc = cur.fetchone()
        if rc and rc[0]:
            reply = int(rc[0])

        cur.close()

        return reply

    def get_job(self, id):

        cur = self.getDB().cursor()    
        d = {}
        cur.execute("SELECT jobid, version, revision, options, jobStatus, "
                    "userId, uploaded, removed FROM tbljobs WHERE " +
                    "jobId = %s;", [id])
        rc = cur.fetchone()
        if rc:
            d = app.utils.parse_job(rc,cur)
       
        cur.close()
      
        return d
    
    def lookup_detailid(self, jobid, phase, test):

        reply = -1
     
        db = self.getDB()

        cur = db.cursor()

        cur.execute("SELECT detailid from tblResults WHERE jobid = %s AND "
                    "phase = %s AND test = %s", [jobid, phase, test])

        rc = cur.fetchone()
        if rc and rc[0]:
            reply = int(rc[0])
            
        cur.close()

        return reply


import app.api
import app.ui
import app.compat
import app.signal
