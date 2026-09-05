// Reset injection packet module
#include <stdlib.h>
#include <Windows.h>
#include "iup.h"
#include "common.h"
#define NAME "reset"

static const unsigned int TCP_MIN_SIZE = sizeof(WINDIVERT_IPHDR) + sizeof(WINDIVERT_TCPHDR);

static Ihandle *inboundCheckbox, *outboundCheckbox, *chanceInput, *rstButton;

static volatile short resetEnabled = 0,
    resetInbound = 1, resetOutbound = 1,
    chance = 0, // [0-10000]
    setNextCount = 0;


static int resetSetRSTNextButtonCb(Ihandle *ih) {
    UNREFERENCED_PARAMETER(ih);

    if (!(*resetModule.enabledFlag)) {
        return IUP_DEFAULT;
    }

    InterlockedIncrement16(&setNextCount);

    return IUP_DEFAULT;
}

static Ihandle* resetSetupUI() {
    Ihandle *dupControlsBox = IupHbox(
        rstButton = IupButton("RST next packet", NULL),
        inboundCheckbox = IupToggle("Inbound", NULL),
        outboundCheckbox = IupToggle("Outbound", NULL),
        IupLabel("Chance(%):"),
        chanceInput = IupText(NULL),
        NULL
        );

    IupSetAttribute(chanceInput, "VISIBLECOLUMNS", "4");
    IupSetAttribute(chanceInput, "VALUE", "0");
    IupSetCallback(chanceInput, "VALUECHANGED_CB", uiSyncChance);
    IupSetAttribute(chanceInput, SYNCED_VALUE, (char*)&chance);
    IupSetCallback(inboundCheckbox, "ACTION", (Icallback)uiSyncToggle);
    IupSetAttribute(inboundCheckbox, SYNCED_VALUE, (char*)&resetInbound);
    IupSetCallback(outboundCheckbox, "ACTION", (Icallback)uiSyncToggle);
    IupSetAttribute(outboundCheckbox, SYNCED_VALUE, (char*)&resetOutbound);
    IupSetCallback(rstButton, "ACTION", resetSetRSTNextButtonCb);
    IupSetAttribute(rstButton, "PADDING", "4x");

    // enable by default to avoid confusing
    IupSetAttribute(inboundCheckbox, "VALUE", "ON");
    IupSetAttribute(outboundCheckbox, "VALUE", "ON");

    if (parameterized) {
        setFromParameter(inboundCheckbox, "VALUE", NAME"-inbound");
        setFromParameter(outboundCheckbox, "VALUE", NAME"-outbound");
        setFromParameter(chanceInput, "VALUE", NAME"-chance");
    }

    return dupControlsBox;
}

static void resetStartup() {
    LOG("reset enabled");
    InterlockedExchange16(&setNextCount, 0);
}

static void resetCloseDown(PacketNode *head, PacketNode *tail) {
    UNREFERENCED_PARAMETER(head);
    UNREFERENCED_PARAMETER(tail);
    LOG("reset disabled");
    InterlockedExchange16(&setNextCount, 0);
}

static short resetProcess(PacketNode *head, PacketNode *tail) {
    short reset = FALSE;
    PacketNode *pac = head->next;
    while (pac != tail) {
        if (checkDirection(pac->addr.Outbound, resetInbound, resetOutbound)
            && pac->packetLen > TCP_MIN_SIZE
            && (setNextCount || calcChance(chance)))
        {
            PWINDIVERT_TCPHDR pTcpHdr;
            WinDivertHelperParsePacket(
                pac->packet,
                pac->packetLen,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                &pTcpHdr,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL);

            if (pTcpHdr != NULL) {
                LOG("injecting reset w/ chance %.1f%%", chance/100.0);
                pTcpHdr->Rst = 1;
                WinDivertHelperCalcChecksums(pac->packet, pac->packetLen, NULL, 0);

                reset = TRUE;
                if (setNextCount > 0) {
                    InterlockedDecrement16(&setNextCount);
                }
            }
        }
        
        pac = pac->next;
    }
    return reset;
}

Module resetModule = {
    "Set TCP RST",
    NAME,
    (short*)&resetEnabled,
    resetSetupUI,
    resetStartup,
    resetCloseDown,
    resetProcess,
    // runtime fields
    0, 0, NULL
};
void clumzy_apply_reset(int inbound, int outbound, float chance_pct) {
    if (chance_pct > 100.0f) chance_pct = 100.0f;
    if (chance_pct < 0.0f) chance_pct = 0.0f;
    InterlockedExchange16((short*)&resetInbound, I2S(inbound ? 1 : 0));
    InterlockedExchange16((short*)&resetOutbound, I2S(outbound ? 1 : 0));
    InterlockedExchange16((short*)&chance, (short)(chance_pct * 100.0f));
    if (inboundCheckbox) IupSetAttribute(inboundCheckbox, "VALUE", inbound ? "ON" : "OFF");
    if (outboundCheckbox) IupSetAttribute(outboundCheckbox, "VALUE", outbound ? "ON" : "OFF");
    if (chanceInput) {
        char buf[16];
        sprintf(buf, "%.1f", chance_pct);
        IupSetAttribute(chanceInput, "VALUE", buf);
    }
}

void clumzy_apply_reset_next(void) {
    InterlockedIncrement16(&setNextCount);
}

void Set_Reset_inboundCheckbox(const char* value) {
    clumzySetToggle(inboundCheckbox, &resetInbound, value);
}
void Set_Reset_outboundCheckbox(const char* value) {
    clumzySetToggle(outboundCheckbox, &resetOutbound, value);
}
void Set_Reset_chanceInput(const char* value) {
    clumzySetChance(chanceInput, &chance, value);
}