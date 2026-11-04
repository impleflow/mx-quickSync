package com.impleflow.dev;

import psdi.server.AppService;
import psdi.server.MXServer;
import psdi.util.MXException;

import java.rmi.RemoteException;

public class XQuickSync extends AppService {

    public XQuickSync(MXServer mxServer) throws RemoteException {
        super(mxServer);
    }

    public XQuickSync() throws RemoteException {}

    @Override
    public void init() {
        getServiceLogger().info("com.impleflow.dev.XQuickSync.init()");
        super.init();
        try {
            MXServer.getMXServer().reloadMaximoCache("ROUTER", true);
        } catch (MXException | RemoteException e) {
            getServiceLogger().error("com.impleflow.dev.XQuickSync.init() Error", e);
        }
    }
}
