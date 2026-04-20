#include <iostream>
#include <fstream>
using namespace std;
ifstream fin("ciffrecv.in");
ofstream fout("ciffrecv.out");
int main()
{
    int  v[100] = {0}, x, i;

    while (fin >> x)
    {
        v[x]++;
    }
    for (i = 8; i > 2; i++)
        if (v[i] % 2 != 0 && v[i] == 2)
        {
            fout << v[i] << i;
        }
    fin.close();
    fout.close();
}