# SMT4ModPlant GUI Orchestrator

**SMT4ModPlant** is a desktop tool for resource matching and B2MML master recipe generation in modular production plants. It parses **B2MML General Recipes**, reads **Asset Administration Shell (AAS)** capability data, and uses the **Z3 SMT solver** to calculate feasible resource assignments.

The application provides a PyQt-based GUI for running calculations, reviewing all valid solutions, ranking solutions by weighted cost, exporting master recipes, validating generated XML files, and inspecting execution logs.

---

## 🌟 Key Features

* **SMT-based resource matching**: Matches recipe requirements against AAS capabilities using **Z3**.
* **Two result modes**:
  * **All Results**: Computes all valid assignments and displays them in the results table.
  * **Weighted Sorted Results**: Computes all valid assignments and ranks them by weighted Energy Cost, Use Cost, and CO2 Footprint.
* **Master Recipe export**: Exports one or multiple selected solutions as **B2MML Master Recipe XML** files.
* **Recipe validation tools**:
  * **XSD validation** for generated or external Master Recipe XML files.
  * **Parameter validation** against parsed AAS capabilities.
  * Detailed in-app issue list showing validation failures, locations, and reasons.
* **Execution log page**: Displays parser, validation, and solver messages for troubleshooting.
* **Modern GUI**: Built with **PyQt6** and **PyQt6-Fluent-Widgets** using a dark Fluent-style interface.
* **Configurable export and weighting**: Choose a custom export directory and adjust the weighted cost factors directly in the Home page.

---

## 📥 Included Example Data

The repository already contains sample files for quick testing:

* **General Recipe**: `GeneralRecipe/ExampleGeneralRecipe.xml`
* **AAS XML samples**: `AAS/XML/`
* **AASX samples**: `AAS/AASX/`
* **XSD schema files**: `Schema/`

---

## 🛠️ Installation

### Prerequisites

* **Python 3.10+**

### Install Dependencies

Run the following commands in your terminal:

```bash
pip install z3-solver PyQt6 lxml
pip install "PyQt6-Fluent-Widgets[full]" -i https://pypi.org/simple/
```

---

## ▶️ Run from Source

```bash
python gui_main.py
```

The application opens with three navigation pages:

* **Home**
* **Recipe Validator**
* **Log**

---

## 🚀 How to Use

### 1. Select Input Files

On the **Home** page:

* Choose a **General Recipe XML** file.
* Choose a **Resources Directory** containing AAS files in `.xml`, `.aasx`, or `.json` format.

### 2. Choose Result Mode

Select one of the two available solution modes:

* **Get All Results**
* **Get All Results Sorted by Weighted Cost**

When weighted sorting is enabled, the weight editor is expanded automatically.

### 3. Configure Export Path and Weights

Still on the **Home** page:

* Keep the default export location in **Downloads**, or switch to a custom export directory.
* In weighted mode, adjust:
  * **Energy Cost Weight**
  * **Use Cost Weight**
  * **CO2 Footprint Weight**

### 4. Run the Calculation

Click **Start Calculation** to begin parsing and solving.

* The progress bar shows calculation progress.
* The **Results** panel slides open automatically when the run finishes.

### 5. Review and Export Solutions

In the **Results** panel:

* Review all returned solutions in a table view.
* In weighted mode, solutions are grouped and labeled with their total weighted score.
* Select one or more solutions using the checkboxes.
* Click **Export Selected** to generate one or more `MasterRecipe_Sol_<id>.xml` files.

---

## ✅ Recipe Validator

The **Recipe Validator** page provides two standalone checks:

### 1. Validate Master Recipe

* Select a Master Recipe XML file.
* Select an XSD schema folder.
* The application validates the XML against the detected root schema and shows the result in the status area.

### 2. Run Parameter Validation

* Select a Master Recipe XML file.
* If calculation context is already available from the Home page, the validator reuses the parsed resource data.
* Otherwise, select a resource folder and the tool parses the AAS files on demand.
* The validator checks whether parameter IDs in the XML can be resolved against the available AAS capability UUIDs.

When validation fails, the page shows a detailed issue list below the status summary.

---

## 🧾 Execution Log

The **Log** page displays runtime messages from:

* recipe parsing
* AAS parsing
* solver execution
* weighted sorting
* export operations
* validation workflows

This page is useful for understanding why a run failed or which files were processed.

---

## 👥 Contributors

* **Bowen Chen**, RWTH Aachen, Chair of Information and Automation Systems for Process and Material Technology
* **Michael Winter**, RWTH Aachen, Chair of Information and Automation Systems for Process and Material Technology
* **Yafan Wu**, RWTH Aachen

---

## 📄 License & Acknowledgments

### Project License

The source code of **SMT4ModPlant** is released under the **[MIT License](LICENSE.txt)**.

### Third-Party Components

This project uses third-party libraries distributed under their respective licenses:

* **[PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)**
  * Used for the graphical user interface
  * Licensed under **GPLv3** for non-commercial use
* **[Z3 Theorem Prover](https://github.com/Z3Prover/z3)**
  * Used for SMT solving and optimization
  * Licensed under the **MIT License**
