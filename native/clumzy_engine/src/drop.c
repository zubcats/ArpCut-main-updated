// dropping packet module
#include <stdlib.h>
#include <stdio.h>
#include <Windows.h>
#include "iup.h"
#include "common.h"
#define NAME "drop"

static Ihandle *inboundCheckbox, *outboundCheckbox, *chanceInput;

static volatile short dropEnabled = 0,
    dropInbound = 1, dropOutbound = 1,
    chance = 1000; // [0-10000]


static Ihandle* dropSetupUI() {
    Ihandle *dropControlsBox = IupHbox(
        inboundCheckbox = IupToggle("Inbound", NULL),
        outboundCheckbox = IupToggle("Outbound", NULL),
        IupLabel("Chance(%):"),
        chanceInput = IupText(NULL),
        NULL
    );

    IupSetAttribute(chanceInput, "VISIBLECOLUMNS", "4");
    IupSetAttribute(chanceInput, "VALUE", "87.0");
    IupSetCallback(chanceInput, "VALUECHANGED_CB", uiSyncChance);
    IupSetAttribute(chanceInput, SYNCED_VALUE, (char*)&chance);
    IupSetCallback(inboundCheckbox, "ACTION", (Icallback)uiSyncToggle);
    IupSetAttribute(inboundCheckbox, SYNCED_VALUE, (char*)&dropInbound);
    IupSetCallback(outboundCheckbox, "ACTION", (Icallback)uiSyncToggle);
    IupSetAttribute(outboundCheckbox, SYNCED_VALUE, (char*)&dropOutbound);

    // enable by default to avoid confusing
    IupSetAttribute(inboundCheckbox, "VALUE", "ON");
    IupSetAttribute(outboundCheckbox, "VALUE", "ON");

    if (parameterized) {
        setFromParameter(inboundCheckbox, "VALUE", NAME"-inbound");
        setFromParameter(outboundCheckbox, "VALUE", NAME"-outbound");
        setFromParameter(chanceInput, "VALUE", NAME"-chance");
    }

    return dropControlsBox;
}

static void dropStartUp() {
    LOG("drop enabled");
}

static void dropCloseDown(PacketNode *head, PacketNode *tail) {
    UNREFERENCED_PARAMETER(head);
    UNREFERENCED_PARAMETER(tail);
    LOG("drop disabled");
}

static short dropProcess(PacketNode *head, PacketNode* tail) {
    int dropped = 0;
    while (head->next != tail) {
        PacketNode *pac = head->next;
        // chance in range of [0, 10000]
        if (checkDirection(pac->addr.Outbound, dropInbound, dropOutbound)
            && calcChance(chance)) {
            LOG("dropped with chance %.1f%%, direction %s",
                chance/100.0, pac->addr.Outbound ? "OUTBOUND" : "INBOUND");
            freeNode(popNode(pac));
            ++dropped;
        } else {
            head = head->next;
        }
    }

    return dropped > 0;
}


Module dropModule = {
    "Drop",
    NAME,
    (short*)&dropEnabled,
    dropSetupUI,
    dropStartUp,
    dropCloseDown,
    dropProcess,
    // runtime fields
    0, 0, NULL
};

void clumzy_apply_drop(int inbound, int outbound, float chance_pct) {
    if (chance_pct > 100.0f) chance_pct = 100.0f;
    if (chance_pct < 0.0f) chance_pct = 0.0f;
    InterlockedExchange16((short*)&dropInbound, I2S(inbound ? 1 : 0));
    InterlockedExchange16((short*)&dropOutbound, I2S(outbound ? 1 : 0));
    InterlockedExchange16((short*)&chance, (short)(chance_pct * 100.0f));
    if (inboundCheckbox) IupSetAttribute(inboundCheckbox, "VALUE", inbound ? "ON" : "OFF");
    if (outboundCheckbox) IupSetAttribute(outboundCheckbox, "VALUE", outbound ? "ON" : "OFF");
    if (chanceInput) {
        char buf[16];
        sprintf(buf, "%.1f", chance_pct);
        IupSetAttribute(chanceInput, "VALUE", buf);
    }
}

void Set_Drop_inboundCheckbox(const char* value) {
    clumzySetToggle(inboundCheckbox, &dropInbound, value);
}
void Set_Drop_outboundCheckbox(const char* value) {
    clumzySetToggle(outboundCheckbox, &dropOutbound, value);
}
void Set_Drop_chanceInput(const char* value) {
    clumzySetChance(chanceInput, &chance, value);
}