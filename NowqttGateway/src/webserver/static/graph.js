fetch("/v1/graph/data")
    .then(res => res.json())
    .then(data => {
        const elements = [];

        data.nodes.forEach(n => {
            elements.push({
                data: {
                    id: n.id,
                    label: n.label,
                    type: n.type
                }
            });
        });

        data.edges.forEach(e => {
            elements.push({
                data: {
                    source: e.source,
                    target: e.target,
                    label: `RSSI: ${e.rssi}`
                }
            });
        });

        const cy = cytoscape({
            container: document.getElementById("cy"),
            elements: elements,
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
                        "text-margin-x": 8,

                        "color": "#000",
                        "font-size": "15px",
                        "text-outline-width": 1,
                        "text-outline-color": "#fff"
                    }
                }, {
                    selector: 'node[type = "gateway"]',
                    style: {
                        "background-color": "#FF4136",
                        "width": 30,
                        "height": 30,
                        "font-weight": "bold"
                    }
                }, {
                    selector: "edge",
                    style: {
                        'label': 'data(label)',
                        'text-rotation': 'autorotate',
                        'text-margin-x': 0,
                        'text-margin-y': -10,
                        'font-size': '12px',
                        'color': '#000',
                        'text-outline-color': '#fff',
                        'text-outline-width': 1,

                        // Arrows
                        'target-arrow-shape': 'triangle',
                        'target-arrow-color': '#aaa',
                        'source-arrow-shape': 'none',
                        'line-color': '#aaa',

                        'curve-style': 'bezier',
                        'control-point-step-size': 40
                    }
                }
            ],
        });

        // Place the gateway node in the center
        const container = document.getElementById("cy");
        const centerX = container.offsetWidth / 2;
        const centerY = container.offsetHeight / 2;

        const gatewayNode = cy.nodes('[type="gateway"]');
        if (gatewayNode.length > 0) {
            gatewayNode.position({ x: centerX, y: centerY });
        }

        // Run the cola layout
        //TODO: would be nice to have a layout that spreads out the nodes so that edges do only overlap if really needed
        cy.layout({
            name: 'cola',
            nodeSpacing: 120,      // min distance between nodes
            edgeLengthVal: 300,    // base edge length
            animate: true,
            randomize: false,
            infinite: false,
            avoidOverlap: true,
            centerGraph: true
        }).run();

        // Optional: fit graph to container
        cy.fit(cy.nodes(), 50); // 50px padding
    });
