#include <stdlib.h>
#include <windows.h>

int main()
{
    // Hide Console Window
    ShowWindow(GetConsoleWindow(), SW_HIDE);
    
    // Start ZubCut.exe in a detached process
    system("start \"\" ZubCut");
    return 0;
}