#include <Windows.h>
#include "iup.h"
#include "common.h"
#define NAME "disconnect"

static Ihandle* inboundCheckbox, * outboundCheckbox;

static volatile short disconnectEnabled = 0;
static volatile short disconnectInbound = 1;
static volatile short disconnectOutbound = 1;


static Ihandle* disconnectSetupUI() {
    Ihandle* disconnectControlsBox = IupHbox(
        inboundCheckbox = IupToggle("Inbound", NULL),
        outboundCheckbox = IupToggle("Outbound", NULL),
        NULL
    );

    IupSetCallback(inboundCheckbox, "ACTION", (Icallback)uiSyncToggle);
    IupSetAttribute(inboundCheckbox, SYNCED_VALUE, (char*)&disconnectInbound);
    IupSetCallback(outboundCheckbox, "ACTION", (Icallback)uiSyncToggle);
    IupSetAttribute(outboundCheckbox, SYNCED_VALUE, (char*)&disconnectOutbound);

    // Enable by default to avoid confusion
    IupSetAttribute(inboundCheckbox, "VALUE", "ON");
    IupSetAttribute(outboundCheckbox, "VALUE", "ON");

    if (parameterized) {
        setFromParameter(inboundCheckbox, "VALUE", NAME"-dinbound");
        setFromParameter(outboundCheckbox, "VALUE", NAME"-doutbound");
    }

    return disconnectControlsBox;
}

static void disconnectStartUp() {
    startTimePeriod();
}

static void disconnectCloseDown(PacketNode* head, PacketNode* tail) {
    UNREFERENCED_PARAMETER(head);
    UNREFERENCED_PARAMETER(tail);
    endTimePeriod();
}

static short disconnectProcess(PacketNode* head, PacketNode* tail) {
        UNREFERENCED_PARAMETER(tail);
        int dropped = 0;
        PacketNode* current = head->next; // Start from the first real packet

        while (current != tail) {
            PacketNode* next = current->next; // Save the next node before processing

            if (checkDirection(current->addr.Outbound, disconnectInbound, disconnectOutbound)) {
                LOG("Dropped packet with direction %s",
                    current->addr.Outbound ? "OUTBOUND" : "INBOUND");
                freeNode(popNode(current)); // Remove and free the current packet
                ++dropped;
            }

            // Move to the next packet
            current = next;
        }

        return dropped > 0; // Return true if any packets were dropped
        
       /* if (checkDirection(tail->addr.Outbound, disconnectInbound, disconnectOutbound)) {
            insertAfter(tail, head);
            return 1;
        }
        else {
            return 0;
        }*/
}

Module disconnectModule = {
    "Disconnect",
    NAME,
    (short*)&disconnectEnabled,
    disconnectSetupUI,
    disconnectStartUp,
    disconnectCloseDown,
    disconnectProcess,
    // runtime fields
    0, 0, NULL
};

void clumzy_apply_disconnect(int inbound, int outbound) {
    InterlockedExchange16((short*)&disconnectInbound, I2S(inbound ? 1 : 0));
    InterlockedExchange16((short*)&disconnectOutbound, I2S(outbound ? 1 : 0));
    if (inboundCheckbox) IupSetAttribute(inboundCheckbox, "VALUE", inbound ? "ON" : "OFF");
    if (outboundCheckbox) IupSetAttribute(outboundCheckbox, "VALUE", outbound ? "ON" : "OFF");
}

void Set_Disconnect_inboundCheckbox(const char* value) {
    clumzySetToggle(inboundCheckbox, &disconnectInbound, value);
}

void Set_Disconnect_outboundCheckbox(const char* value) {
    clumzySetToggle(outboundCheckbox, &disconnectOutbound, value);
}
