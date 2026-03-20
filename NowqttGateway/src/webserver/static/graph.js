// Initialize Cytoscape once
const cy = cytoscape({
    container: document.getElementById("cy"),
    elements: [],
    style: [
        {
            selector: "node",
            style: {
                "label": "data(label)",
                "background-color": "#0074D9",
                "width": 20,
                "height": 20,

                "text-valign": "center",
                "text-halign": "right",
                "text-margin-x": 12, // ⬅️ increased spacing

                "color": "#000",
                "font-size": "15px",
                "text-outline-width": 1,
                "text-outline-color": "#fff"
            }
        },
        {
            selector: 'node[type = "gateway"]',
            style: {
                "background-color": "#FF4136",
                "width": 30,
                "height": 30,
                "font-weight": "bold"
            }
        },
        {
            selector: "edge",
            style: {
                'label': 'data(label)',
                'text-rotation': 'autorotate',
                'text-margin-y': -10,
                'font-size': '12px',
                'color': '#000',

                // ⬇️ label readability improvement
                'text-outline-color': '#fff',
                'text-outline-width': 1,
                'text-background-color': '#fff',
                'text-background-opacity': 1,
                'text-background-padding': 2,

                'target-arrow-shape': 'triangle',
                'target-arrow-color': '#aaa',
                'line-color': '#aaa',

                'curve-style': 'bezier',
                'control-point-step-size': 60 // ⬅️ slightly more curve separation
            }
        }
    ]
});

let initialized = false;

// Shared layout config (⬅️ improved spacing)
function runLayout() {
    cy.layout({
        name: 'cola',

        nodeSpacing: 200,
        edgeLengthVal: 400,
        edgeLength: 400,

        animate: true,
        randomize: false,
        avoidOverlap: true,
        handleDisconnected: true,

        convergenceThreshold: 0.01,
        maxSimulationTime: 2000,

        centerGraph: true,
        fit: true
    }).run();

    layout.on('layoutstop', () => {
        cy.fit(cy.nodes(), 200); // padding
    });
}

// Main update function
async function updateGraph() {
    try {
        const res = await fetch("/v1/graph/data");
        const data = await res.json();

        const existingNodeIds = new Set(cy.nodes().map(n => n.id()));
        const incomingNodeIds = new Set(data.nodes.map(n => n.id));

        // -------------------
        // REMOVE old nodes
        // -------------------
        cy.nodes().forEach(n => {
            if (!incomingNodeIds.has(n.id())) {
                cy.remove(n);
            }
        });

        // -------------------
        // ADD new nodes
        // -------------------
        let newNodeAdded = false;

        data.nodes.forEach(n => {
            if (!existingNodeIds.has(n.id)) {
                cy.add({
                    group: "nodes",
                    data: {
                        id: n.id,
                        label: n.label,
                        type: n.type
                    }
                });
                newNodeAdded = true;
            }
        });

        // -------------------
        // EDGE HANDLING
        // -------------------
        const existingEdges = new Map();
        cy.edges().forEach(e => {
            existingEdges.set(e.id(), e);
        });

        const seenEdges = new Set();

        data.edges.forEach(e => {
            const id = `${e.source}-${e.target}`;
            seenEdges.add(id);

            if (existingEdges.has(id)) {
                existingEdges.get(id).data("label", `RSSI: ${e.rssi}`);
            } else {
                cy.add({
                    group: "edges",
                    data: {
                        id,
                        source: e.source,
                        target: e.target,
                        label: `RSSI: ${e.rssi}`
                    }
                });
            }
        });

        // -------------------
        // REMOVE old edges
        // -------------------
        cy.edges().forEach(e => {
            if (!seenEdges.has(e.id())) {
                cy.remove(e);
            }
        });

        // -------------------
        // INITIAL SETUP
        // -------------------
        if (!initialized) {
            runLayout();
            // cy.fit(cy.nodes(), 80); // ⬅️ more padding

            initialized = true;
        }

        // -------------------
        // LAYOUT ONLY IF NEW NODES
        // -------------------
        if (newNodeAdded) {
            runLayout();
        }

    } catch (err) {
        console.error("Graph update failed:", err);
    }
}

// Initial load
updateGraph();

// Poll every 30 seconds
setInterval(updateGraph, 30000);