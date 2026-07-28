from collections import deque


_NODE_COLLECTIONS = ("Inputs", "Intermediates", "Outputs", "ProcessElements")


def _node_id(node, collection_name):
    if not isinstance(node, dict):
        raise ValueError(
            "Invalid General Recipe DirectedLinks: "
            f"{collection_name} contains a non-object entry."
        )

    value = node.get("ID")
    node_id = str(value).strip() if value is not None else ""
    if not node_id:
        raise ValueError(
            "Invalid General Recipe DirectedLinks: "
            f"{collection_name} contains an entry without an ID."
        )
    return node_id


def _reachable_from(starts, adjacency):
    reached = set(starts)
    pending = deque(starts)
    while pending:
        node_id = pending.popleft()
        for successor in adjacency[node_id]:
            if successor not in reached:
                reached.add(successor)
                pending.append(successor)
    return reached


def _validate_acyclic(node_ids, adjacency):
    indegree = {node_id: 0 for node_id in node_ids}
    for successors in adjacency.values():
        for successor in successors:
            indegree[successor] += 1

    pending = deque(
        node_id for node_id, degree in indegree.items() if degree == 0
    )
    visited = 0
    while pending:
        node_id = pending.popleft()
        visited += 1
        for successor in adjacency[node_id]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                pending.append(successor)

    if visited != len(node_ids):
        raise ValueError(
            "Invalid General Recipe DirectedLinks: the graph contains a cycle."
        )


def _next_process_elements(start_id, process_ids, adjacency):
    successors = set()
    visited = set()
    pending = deque(adjacency[start_id])

    while pending:
        node_id = pending.popleft()
        if node_id in process_ids:
            successors.add(node_id)
            continue
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(adjacency[node_id])

    return successors


def order_process_elements_by_directed_links(recipe_data):
    """
    Return the original ProcessElement objects in their DirectedLinks order.

    Material nodes between ProcessElements are traversed but do not become
    execution steps. Only a single, input-to-output anchored phase chain is
    accepted.
    """
    if not isinstance(recipe_data, dict):
        raise ValueError(
            "Invalid General Recipe DirectedLinks: recipe data must be an object."
        )

    nodes_by_id = {}
    ids_by_collection = {}
    for collection_name in _NODE_COLLECTIONS:
        collection = recipe_data.get(collection_name) or []
        if not isinstance(collection, list):
            raise ValueError(
                "Invalid General Recipe DirectedLinks: "
                f"{collection_name} must be a list."
            )

        collection_ids = []
        for node in collection:
            node_id = _node_id(node, collection_name)
            if node_id in nodes_by_id:
                raise ValueError(
                    "Invalid General Recipe DirectedLinks: "
                    f"duplicate node ID '{node_id}'."
                )
            nodes_by_id[node_id] = node
            collection_ids.append(node_id)
        ids_by_collection[collection_name] = collection_ids

    process_ids_in_source_order = ids_by_collection["ProcessElements"]
    if not process_ids_in_source_order:
        return []

    input_ids = set(ids_by_collection["Inputs"])
    output_ids = set(ids_by_collection["Outputs"])
    process_ids = set(process_ids_in_source_order)

    if not input_ids:
        raise ValueError(
            "Invalid General Recipe DirectedLinks: at least one recipe input "
            "is required for a recipe with ProcessElements."
        )
    if not output_ids:
        raise ValueError(
            "Invalid General Recipe DirectedLinks: at least one recipe output "
            "is required for a recipe with ProcessElements."
        )

    links = recipe_data.get("DirectedLinks") or []
    if not isinstance(links, list) or not links:
        raise ValueError(
            "Invalid General Recipe DirectedLinks: no links were defined for "
            "the ProcessElements."
        )

    adjacency = {node_id: set() for node_id in nodes_by_id}
    reverse_adjacency = {node_id: set() for node_id in nodes_by_id}
    link_ids = set()

    for index, link in enumerate(links, start=1):
        if not isinstance(link, dict):
            raise ValueError(
                "Invalid General Recipe DirectedLinks: "
                f"link #{index} is not an object."
            )

        link_id_value = link.get("ID")
        link_id = (
            str(link_id_value).strip()
            if link_id_value is not None
            else ""
        )
        if link_id:
            if link_id in link_ids:
                raise ValueError(
                    "Invalid General Recipe DirectedLinks: "
                    f"duplicate link ID '{link_id}'."
                )
            link_ids.add(link_id)

        from_value = link.get("FromID")
        to_value = link.get("ToID")
        from_id = str(from_value).strip() if from_value is not None else ""
        to_id = str(to_value).strip() if to_value is not None else ""
        link_label = f"'{link_id}'" if link_id else f"#{index}"

        if not from_id or not to_id:
            raise ValueError(
                "Invalid General Recipe DirectedLinks: "
                f"link {link_label} requires FromID and ToID."
            )
        for endpoint_name, endpoint_id in (
            ("FromID", from_id),
            ("ToID", to_id),
        ):
            if endpoint_id not in nodes_by_id:
                raise ValueError(
                    "Invalid General Recipe DirectedLinks: "
                    f"link {link_label} has unknown {endpoint_name} "
                    f"'{endpoint_id}'."
                )

        adjacency[from_id].add(to_id)
        reverse_adjacency[to_id].add(from_id)

    _validate_acyclic(nodes_by_id, adjacency)

    reachable_from_inputs = _reachable_from(input_ids, adjacency)
    can_reach_outputs = _reachable_from(output_ids, reverse_adjacency)
    for process_id in process_ids_in_source_order:
        if process_id not in reachable_from_inputs:
            raise ValueError(
                "Invalid General Recipe DirectedLinks: ProcessElement "
                f"'{process_id}' is not reachable from a recipe input."
            )
        if process_id not in can_reach_outputs:
            raise ValueError(
                "Invalid General Recipe DirectedLinks: ProcessElement "
                f"'{process_id}' cannot reach a recipe output."
            )

    process_successors = {
        process_id: _next_process_elements(
            process_id,
            process_ids,
            adjacency,
        )
        for process_id in process_ids
    }
    process_predecessors = {process_id: set() for process_id in process_ids}
    for process_id, successors in process_successors.items():
        if len(successors) > 1:
            raise ValueError(
                "Invalid General Recipe DirectedLinks: ProcessElement "
                f"'{process_id}' branches to multiple ProcessElements."
            )
        for successor in successors:
            process_predecessors[successor].add(process_id)

    for process_id, predecessors in process_predecessors.items():
        if len(predecessors) > 1:
            raise ValueError(
                "Invalid General Recipe DirectedLinks: ProcessElement "
                f"'{process_id}' joins multiple ProcessElements."
            )

    roots = [
        process_id
        for process_id in process_ids
        if not process_predecessors[process_id]
    ]
    if len(roots) != 1:
        raise ValueError(
            "Invalid General Recipe DirectedLinks: ProcessElements must form "
            "one linear chain."
        )

    ordered_ids = []
    current_id = roots[0]
    while current_id is not None:
        ordered_ids.append(current_id)
        successors = process_successors[current_id]
        current_id = next(iter(successors)) if successors else None

    if len(ordered_ids) != len(process_ids):
        raise ValueError(
            "Invalid General Recipe DirectedLinks: ProcessElements must form "
            "one connected linear chain."
        )

    return [nodes_by_id[process_id] for process_id in ordered_ids]
