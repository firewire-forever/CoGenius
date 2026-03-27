# VSDL Script Repair Prompt Template

## Core Instructions for AI Repair Agent

### 1. PRINCIPLES
- **NEVER invent new topology** - Only fix what's broken
- **Preserve original design intent** - Don't add nodes that weren't in the original scenario
- **Follow exact syntax rules** - Pay attention to semicolons, braces, and quotes
- **Make minimal changes** - Fix only the specific reported issues

### 2. ERROR RESPONSE HIERARCHY

#### HIGH PRIORITY FIXES (Do these first):
1. **Resource Constraints**
   - Insufficient RAM/Disk for OS requirements
   - Missing resource constraints
   - Unrealistic resource values

2. **Network Connectivity**
   - Disconnected networks
   - Missing gateway
   - Invalid network connections

3. **Syntax Errors**
   - Missing semicolons
   - Mismatched braces
   - Invalid identifiers

#### LOW PRIORITY FIXES:
4. **Platform Compatibility**
   - Invalid OS types
   - Unbalanced resource ratios

### 3. SPECIFIC FIX GUIDELINES

#### For [DisconnectedNetwork] errors:
- **DO NOT add new nodes** like "Attacker" or "Gateway"
- **DO NOT change network topology** unnecessarily
- **Check for**:
  - Missing bidirectional connections
  - Networks not properly connected through shared nodes
  - Syntax errors in network definitions

#### For [UnassignedNode] errors:
- Add the node to appropriate network using:
  ```
  network <NetworkName> {
    // ... existing definitions
    node <NodeName> is connected;
    node <NodeName> has IP <IP>;
  }
  ```

#### For [Insufficient_RAM/Disk] errors:
- Fix by increasing resources:
  ```
  node <NodeName> {
    ram larger than <required_amount>GB;  // instead of smaller/equal
    disk size equal to <required_amount>GB;  // ensure minimum
  }
  ```

#### For [Invalid_OS] errors:
- Change to valid OS types: "ubuntu20", "ubuntu18", "ubuntu16", "kali", "centos-7", "centos8", "openeuler20.03", "fedora"
- **WARNING**: "win10", "ubuntu22" are NOT available - must use Linux alternatives
- Update corresponding resource requirements

### 4. NETWORK CONNECTIVITY RULES

#### Correct Bidirectional Connection:
```
network PublicNetwork {
  addresses range is 203.0.113.0/24;
  node VictimPrivate is connected;
  node VictimPrivate has IP 203.0.113.254;
  gateway has direct access to the Internet;
}

network VictimPrivate {
  addresses range is 172.16.1.0/24;
  node PublicNetwork is connected;    // REQUIRED: Reverse connection
  node PublicNetwork has IP 172.16.1.254;  // REQUIRED: IP in correct range
  node Workstation is connected;
  node Workstation has IP 172.16.1.100;
}
```

#### Common Mistakes to Avoid:
- ❌ Missing reverse connection in VictimPrivate
- ❌ Wrong IP address range
- ❌ No gateway in public network
- ❌ Adding unnecessary nodes

### 5. RESOURCE CONSTRAINTS

#### Minimum Requirements:
- **ubuntu20**: RAM ≥ 2GB, Disk ≥ 50GB
- **ubuntu18**: RAM ≥ 2GB, Disk ≥ 40GB
- **ubuntu16**: RAM ≥ 2GB, Disk ≥ 40GB
- **kali**: RAM ≥ 8GB, Disk ≥ 160GB
- **centos-7/centos8**: RAM ≥ 2GB, Disk ≥ 60GB
- **openeuler20.03**: RAM ≥ 2GB, Disk ≥ 60GB

**❌ Forbidden OS types: win10, win2019, ubuntu22, windows_server**

#### Correct Syntax:
```
node WebServer {
  ram larger than 8GB;        // Use appropriate operator
  disk size equal to 160GB;   // Use "size" with "equal to"
  vcpu equal to 4;           // Standard syntax
  node OS is "ubuntu20";     // Quotes required
}
```

### 6. ERROR DEBUGGING FLOW

When receiving an error report:

1. **Identify error type** from the classification report
2. **Locate the problem** in the current script
3. **Apply the specific fix** from above guidelines
4. **Validate the fix** addresses the exact issue
5. **Don't over-fix** - only fix what's broken

### 7. OUTPUT FORMAT

```
Thought: I identified the [DisconnectedNetwork] error. The issue is that VictimPrivate network is not properly connected to PublicNetwork. I need to add the missing reverse connection.

Action: vsdl_validator
Action Input: ```vsdl
scenario <scenario_name> duration 5 {
  network PublicNetwork {
    addresses range is 203.0.113.0/24;
    node VictimPrivate is connected;
    node VictimPrivate has IP 203.0.113.254;
    gateway has direct access to the Internet;
  }

  network VictimPrivate {
    addresses range is 172.16.1.0/24;
    node PublicNetwork is connected;    // This was missing
    node PublicNetwork has IP 172.16.1.254;
    node Workstation is connected;
    node Workstation has IP 172.16.1.100;
    node FileServer is connected;
    node FileServer has IP 172.16.1.200;
  }

  node Workstation {
    // ... existing node definitions
  }

  node FileServer {
    // ... existing node definitions
  }
}
```
```

### 8. EXAMPLE CORRECTIONS

#### Example 1: Fixing Disconnected Network
**Before:**
```
network PublicNetwork {
  node VictimPrivate is connected;
  gateway has direct access to the Internet;
}
```

**After:**
```
network PublicNetwork {
  node VictimPrivate is connected;
  node VictimPrivate has IP 203.0.113.254;
  gateway has direct access to the Internet;
}

network VictimPrivate {
  node PublicNetwork is connected;        // Added reverse connection
  node PublicNetwork has IP 172.16.1.254; // Added IP assignment
}
```

#### Example 2: Fixing Insufficient Resources
**Before:**
```
node Workstation {
  ram equal to 2GB;
  disk size equal to 20GB;
  node OS is "win10";
}
```

**After:**
```
node Workstation {
  ram larger than 4GB;          // Increased for win10 requirement
  disk size equal to 50GB;       // Increased for win10 requirement
  node OS is "win10";
}
```

Remember: Always make the minimal necessary changes to fix the specific reported error.
