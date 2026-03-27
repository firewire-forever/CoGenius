print(">>> UNSAT ANALYZER v3 LOADED (True Graph + SMT Aligned) <<<")

def analyze_unsat(vsdl_script: str) -> list[str]:
    reasons = []

    # ============================================================
    # 1. Parse model
    # ============================================================

    networks = {}            # net -> set(nodes)
    nodes = set()
    node_to_net = {}         # node -> net (VSDLC: exactly one)
    
    node_os = {}
    node_disk = {}
    node_ram = {}
    node_vcpu = {}

    lines = vsdl_script.splitlines()
    current_network = None
    current_node = None

    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        # network begin
        if line.startswith("network ") and "{" in line:
            name = line.split()[1]
            networks[name] = set()
            current_network = name
            current_node = None
            continue

        # node begin
        if line.startswith("node ") and "{" in line:
            name = line.split()[1]
            nodes.add(name)
            current_node = name
            current_network = None
            continue

        if line == "}":
            current_network = None
            current_node = None
            continue

        # connection
        if "is connected" in line:
            parts = line.split()
            n = parts[1]

            if not current_network:
                reasons.append(
                    f"[InvalidConnectionScope] Line {lineno}: {raw.strip()}"
                )
                continue

            networks[current_network].add(n)

            # In VSDL, a node can appear in multiple networks (acting as a router)
            # So we allow a node to be in multiple networks
            if n not in node_to_net:
                node_to_net[n] = current_network
            # If the node is already in another network, that's fine - it's a router

        # resources
        if current_node:
            if line.startswith("disk size"):
                node_disk[current_node] = int(line.split()[-1].replace("GB", "").replace(";", ""))
            elif line.startswith("ram"):
                node_ram[current_node] = int(line.split()[-1].replace("GB", "").replace(";", ""))
            elif line.startswith("vcpu"):
                node_vcpu[current_node] = int(line.split()[-1].replace(";", ""))
            elif line.startswith("node OS"):
                node_os[current_node] = line.split('"')[1]

    # ============================================================
    # 2. Core VSDLC topology constraints
    # ============================================================

    # every node must be in exactly one network
    for n in nodes:
        if n not in node_to_net:
            reasons.append(f"[UnassignedNode] Node '{n}' is in no network")

    # every network must have at least one node
    for net, ns in networks.items():
        if not ns:
            reasons.append(f"[EmptyNetwork] Network '{net}' has no nodes")

    # ============================================================
    # 3. Network connectivity SMT model
    # ============================================================
    # VSDLC: networks are connected IF they share at least one node

    net_graph = {n: set() for n in networks}

    for node, net in node_to_net.items():
        for other_node, other_net in node_to_net.items():
            if node == other_node:
                continue
            # same node cannot be in two nets, so this only connects through routing nodes
            if net != other_net:
                continue

    # Actually VSDLC connectivity is via routing nodes
    # If a node appears in two networks → it is a router
    routers = {}
    for node, net in node_to_net.items():
        routers.setdefault(node, set()).add(net)

    for node, nets in routers.items():
        if len(nets) > 1:
            for a in nets:
                for b in nets:
                    if a != b:
                        net_graph[a].add(b)

    # DFS on network graph
    if len(networks) > 1:
        visited = set()
        start = next(iter(networks))

        def dfs(x):
            for y in net_graph.get(x, []):
                if y not in visited:
                    visited.add(y)
                    dfs(y)

        visited.add(start)
        dfs(start)

        for net in networks:
            if net not in visited:
                reasons.append(f"[DisconnectedNetwork] '{net}' not reachable")

    # ============================================================
    # 4. Resource SMT constraints
    # ============================================================

    OS_MIN = {
        "win10": {"disk": 20, "ram": 4},
        "ubuntu20": {"disk": 50, "ram": 2},
    }

    for n in nodes:
        os = node_os.get(n)
        if os in OS_MIN:
            req = OS_MIN[os]
            if node_disk.get(n, 0) < req["disk"]:
                reasons.append(
                    f"[DiskTooSmall] {n}: {node_disk.get(n,0)}GB < {req['disk']}GB for {os}"
                )
            if node_ram.get(n, 0) < req["ram"]:
                reasons.append(
                    f"[RamTooSmall] {n}: {node_ram.get(n,0)}GB < {req['ram']}GB for {os}"
                )

    # ============================================================
    # 5. SMT-style UNSAT core
    # ============================================================

    if not reasons:
        reasons.append(
            "[UNSAT-Core-Unknown] All structural and resource constraints SAT; "
            "UNSAT must originate from higher-level VSDLC rules."
        )

    return reasons
