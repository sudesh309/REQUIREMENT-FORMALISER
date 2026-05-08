/* Sample SysML v2 model: a small vehicle with parts, ports, and a connection.
   Mirrors the kind of model one would build in Cameo SysML 1.6 (Block + IBD). */

package Vehicles {

    attribute def Mass;
    attribute def Power;

    port def MechanicalPort;
    port def ElectricalPort;

    part def Engine {
        attribute power : Power;
        port shaft : MechanicalPort;
    }

    part def Battery {
        attribute capacity : Mass;
        port terminal : ElectricalPort;
    }

    part def Transmission {
        port input  : MechanicalPort;
        port output : MechanicalPort;
    }

    part def Vehicle {
        attribute mass : Mass;
        part engine        : Engine;
        part transmission  : Transmission;
        part battery       : Battery;
    }

    enum def DriveMode { Eco; Normal; Sport; }
}
