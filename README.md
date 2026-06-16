# Open//Structures

**A Transparent 3D Structural Analysis Engine for Learning Finite Element Methods**

Open//Structures bridges the gap between simplified 2D textbook problems and complex commercial "black box" software. Built as an educational tool, it provides full visibility into the FEM solver logic, making it perfect for civil engineering students learning structural analysis.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-blue.svg)](https://github.com/Open//Structures-Project/Open//Structures/releases)
[![Version](https://img.shields.io/badge/version-v0.655%20Pre--Alpha-orange.svg)](https://github.com/Open//Structures-Project/Open//Structures/releases/latest)

![Open//Structures Main Interface](images/hero-main.png)

---

## ✅ Validation & Accuracy

**Open//Structures has been rigorously validated for mathematical correctness.**

All analysis implementations have been independently verified against industry-standard commercial FEM software and analytical solutions, demonstrating **6-7 decimal place agreement** across all analysis types.

### Validation Results:

| Analysis Type | Feature | Accuracy |
|---------------|---------|----------|
| **Linear Static** | Nodal displacements | ✅ 6+ decimal agreement |
| | Support reactions | ✅ Verified to machine precision |
| | Element internal forces | ✅ Exact match |
| **Modal Analysis** | Natural periods/frequencies | ✅ Identical to 7+ decimals |
| | Mode shapes | ✅ Verified (normalized) |
| | Mass participation factors | ✅ Exact match |
| **Response Spectrum** | Spectral accelerations (TBDY 2018) | ✅ 6+ decimal agreement |
| | Modal combination (CQC/SRSS) | ✅ Validated |
| | Base shear calculations | ✅ Verified |

### Advanced Features Validated:
- ✅ Cardinal insertion points 
- ✅ Rigid end offsets
- ✅ Member releases (moment release for now)
- ✅ Eccentric connections
- ✅ Self-weight
- ✅ 3D Timoshenko beam theory with shear deformation

### Example: Multi-Story Building Test Case

A 3-story steel frame structure (200+ nodes) was modeled and analyzed:

#### Modal Analysis Validation
![Modal Analysis Validation](images/validation/Modal_Validation.png)
*Side-by-side comparison showing identical natural periods across all modes*

**Natural Periods (first 5 modes):**
| Mode | Reference Software | Open//Structures | Difference |
|------|-------------------|-----------|------------|
| 1 | 0.919124 sec | 0.919124 sec | 0.000000 |
| 2 | 0.892762 sec | 0.892762 sec | 0.000000 |
| 3 | 0.580158 sec | 0.580158 sec | 0.000000 |
| 4 | 0.430003 sec | 0.430003 sec | 0.000000 |
| 5 | 0.365274 sec | 0.365274 sec | 0.000000 |

#### Response Spectrum Analysis Validation
![Response Spectrum Validation](images/validation/RSA_Validation.png)
*TBDY 2018 response spectrum analysis showing matching spectral accelerations*

**Spectral Accelerations (first 5 modes):**
| Mode | Period (sec) | Reference Sa (m/s²) | Open//Structures Sa (m/s²) | Difference |
|------|-------------|---------------------|---------------------|------------|
| 1 | 0.919124 | 1.573690 | 1.573692 | 0.000002 |
| 2 | 0.692762 | 2.105810 | 2.105812 | 0.000002 |
| 3 | 0.580158 | 2.514940 | 2.514942 | 0.000002 |
| 4 | 0.430003 | 3.520890 | 3.520891 | 0.000001 |
| 5 | 0.365274 | 3.954540 | 3.954535 | 0.000005 |

### Why This Matters for Learning

Unlike commercial "black box" software, Open//Structures's transparency **combined with validated accuracy** means:
- Students can inspect the math **and trust the results**
- Hand calculations can be verified against a **proven-correct solver**
- Matrix exports can be used for homework **with confidence**
- Understanding is built on **rigorous foundations**

**Note:** Validation performed using academic software licenses for educational comparison purposes only. Open//Structures is an independent open-source implementation and is not affiliated with any commercial software vendor.

---

## 🎯 Why Open//Structures?

**For Students:**
- See exactly how FEM works under the hood
- Inspect stiffness matrices, transformation matrices, and FEF vectors
- Understand the math behind commercial software like SAP2000 or ETABS
- No "black box" - every calculation is transparent
- **Verified accuracy** - results you can trust for learning

**For Educators:**
- Use real 3D problems instead of simplified 2D examples
- Students can verify hand calculations against a **validated solver**
- Export matrices to MATLAB/Python for homework assignments
- Completely free and open to academic use
- **Proven correct** - validated against industry standards

---

## ✨ Key Features

### 🔬 **"Glass Box" FEM Solver**
Unlike commercial software, Open//Structures lets you see everything:
- **12×12 Element Stiffness Matrices [k]** in local coordinates
- **Transformation Matrices [T]** showing global-to-local conversion
- **Fixed End Forces (FEF)** from distributed and point loads
- **Matrix Tool** - Export matrices as JSON for external analysis
- **Free Body Diagrams** for each element showing internal forces

### 🏗️ **Advanced Structural Modeling**
- **3D Timoshenko Beam Theory** with shear deformation effects
- **Rigid End Offsets** and cardinal insertion points (11 positions)
- **Member Releases** (moment/shear/axial) using static condensation
- **Joint Offsets** for eccentric connections
- **True-to-scale 3D extrusions** (I-beams, rectangular, custom shapes)

### 📊 **Multiple Analysis Types**

#### 1️⃣ **Linear Static Analysis**
- Full 3D frame analysis
- Distributed loads, point loads, nodal loads
- Self-weight generation
- Load combinations
- Reaction forces and base shear

#### 2️⃣ **Modal Analysis (Eigenvalue)**
- Shift-invert eigenvalue solver
- Mode shapes visualization with animation
- Modal participation factors (Γx, Γy, Γz)
- Mass participation ratios
- Period and frequency extraction

#### 3️⃣ **Response Spectrum Analysis** 🇹🇷
**Built-in Turkish Seismic Code 2018 (TBDY) Support:**
- Automatic spectrum generation (Horizontal & Vertical)
- Site class effects (ZA, ZB, ZC, ZD, ZE)
- Modal combination: SRSS or CQC
- Directional combination: SRSS or ABS
- Damping correction (Newmark-Hall method)
- Custom response spectrum functions

### 🎨 **Interactive Visualization**
- **3D OpenGL rendering** with hardware acceleration
- **Deformed shape animation** with adjustable speed and scale
- **Multiple view modes**: 3D, XY, XZ, YZ projections
- **Click-to-inspect**: Select any node or element for details
- **Customizable graphics**: Background color, node size, line width, transparency
- **Sound effects** during animation (optional)

### 💾 **Transparent Data Format**
- Projects saved as **human-readable JSON** (.mf files)
- Easy to parse with Python, MATLAB, or Excel
- Export analysis results for post-processing
- Matrix data available for verification

---

## 🖥️ System Requirements

- **OS**: Windows 10/11 (64-bit)
- **RAM**: 4 GB minimum, 8 GB recommended
- **Graphics**: OpenGL 3.3+ capable GPU
- **Disk**: 200 MB installation space

---

## 📥 Installation

### Option 1: Windows Installer (Recommended)
1. Download the latest installer from [Releases](https://github.com/Open//Structures-Project/Open//Structures/releases/latest)
2. Run `Open//Structures_Setup_v0.x.exe`
3. Follow installation wizard
4. Launch from desktop shortcut

**No Python installation required!**

### Option 2: Run from Source (Developers)
```bash
git clone https://github.com/Open//Structures-Project/Open//Structures.git
cd Open//Structures
pip install -r requirements.txt
python app/main.py
```

**Dependencies:**
- Python 3.10+
- PyQt6
- NumPy, SciPy
- PyOpenGL, PyQtGraph
- Matplotlib

---

## 🚀 Quick Start Guide

### 1. Create a New Model
```
File > New Model > Define grid lines (X, Y, Z)
```

### 2. Define Materials & Sections
```
Define > Material Properties... > Add (e.g., Concrete C30, Steel S275)
Define > Section Properties... > Add I-Beam or Rectangular
```

### 3. Draw Structure
```
Draw > Draw Frame/Cable > Click start node, drag to end node
```

### 4. Assign Properties
- **Restraints**: Select nodes → Assign > Joint Restraints...
- **Loads**: Select elements → Assign > Frame Loads...
- **Releases**: Select elements → Assign > Releases Partial Fixity...

### 5. Define Analysis Case
```
Define > Load Cases > Add "DEAD" or "LIVE"
Define > Load Patterns > Set scale factors
```

### 6. Run Analysis
```
Analyze > Run Analysis (F5)
Choose: Linear Static / Modal / Response Spectrum
```

### 7. View Results
- **Deformed Shape**: Display > Show Deformed Shape
- **Animation**: Display > Animate Deformed Shape
- **Reactions**: Display > Show Reactions Table
- **Element Forces**: Right-click element > View Free Body Diagram
- **Matrices**: Right-click element > Matrix

---

## 📖 Educational Use Cases

### For FEM Courses:
1. **Verify hand calculations** - Export stiffness matrix and compare with **validated solver**
2. **Understand transformations** - See how local coordinates convert to global
3. **Study releases** - Learn static condensation by inspecting condensed matrices
4. **Explore Timoshenko theory** - Compare results with/without shear deformation
5. **Trust the results** - Solver validated to 6+ decimal places against commercial software

### For Structural Dynamics:
1. **Modal analysis** - Extract mode shapes and natural frequencies with **proven accuracy**
2. **Response spectrum** - Apply TBDY 2018 or custom spectra with **validated implementation**
3. **Animation** - Visualize mode shapes with breathing effect

### For Seismic Design (Turkey):
1. **TBDY 2018 Compliance** - Built-in spectrum generator (**validated**)
2. **Site effects** - Compare ZA vs ZE site classes
3. **Modal combination** - Study CQC vs SRSS differences with **correct implementation**

---

## 🎓 Sample Problems Included

The `/Example_Project/` folder contains:
- Simple cantilever beam
- 2-story frame structure
- Modal analysis test case

---

## 🔧 Advanced Features

### Matrix Tool
Export element matrices to JSON:
```json
{
  "element_id": "1",
  "k": [[...], [...], ...],  // 12×12 local stiffness
  "t": [[...], [...], ...],  // 12×12 transformation
  "fef": [...]               // Fixed end forces
}
```

### Custom Response Spectrum
Define your own spectrum function:
```
Define > Functions > Response Spectrum
Enter Ss and S1 values from Turkish Hazard Map
```

### Load Combinations
```
Define > Load Cases > Add Combination
COMB1 = 1.2×DEAD + 1.6×LIVE
```

### Unit System Support
- SI: kN, m, °C
- Metric: N, mm, °C
- Imperial: kip, ft, °F
- Turkish: Tonf, m, °C

---

## 🤝 Contributing

This project is currently in **active development** (Pre-Alpha stage). 

**Not accepting code contributions yet**, but feedback is welcome:
- 🐛 **Bug Reports**: [Open an Issue](https://github.com/Open//Structures-Project/Open//Structures/issues)
- 💡 **Feature Requests**: [Start a Discussion](https://github.com/Open//Structures-Project/Open//Structures/discussions)
- 📧 **Contact**: [GitHub Profile](https://github.com/ShaikhAhmedAzad)

---

## 📚 Documentation

Detailed documentation is coming soon. For now:
- Press `F1` in the software for context help
- Check `/docs/` folder for user guides (in development)
- Watch tutorial videos (coming soon)

---

## ⚖️ License

MIT License - Free for educational and non-commercial use.

See [LICENSE](LICENSE) file for details.

---

## 👨‍🎓 Author

**Shaikh Ahmed Azad**  
Civil Engineering Student | Middle East Technical University (METU)  
📧 Contact: [GitHub Profile](https://github.com/ShaikhAhmedAzad)

---

## 🙏 Acknowledgments

- **METU Civil Engineering Department** for academic support
- **Open-source community** for Python/PyQt/NumPy/SciPy libraries
- **Students and professors** who provided feedback during testing and validation

---

## 🔮 Roadmap

**Upcoming Features:**
- [ ] Nonlinear analysis (P-Delta effects)
- [ ] Time history analysis
- [ ] Steel connection design checks
- [ ] Concrete section design (ACI/Eurocode)
- [ ] DXF import/export
- [ ] Python scripting API
- [ ] Extended validation documentation

---

## 📸 Screenshots

| Feature | Preview |
|---------|---------|
| **3D Modeling** | ![Modeling](images/hero-main.png) |
| **Deformed Shape** | ![Results](images/deformed_shape.png) |
| **Modal Animation** | ![Animation](images/Animation.gif) |
| **Response Spectrum** | ![TBDY 2018](images/TBDY_Response_Spectra.png) |

---

## ❓ FAQ

**Q: Is this suitable for real engineering design?**  
A: No - Open//Structures is an **educational tool**. Use commercial software (SAP2000, ETABS, etc.) for actual building design. However, Open//Structures's results are validated to match commercial software accuracy for learning purposes.

**Q: How accurate are the results?**  
A: Open//Structures has been validated against industry-standard commercial FEM software and shows 6-7 decimal place agreement for all analysis types. See the Validation section above for details.

**Q: Can I use Open//Structures for my thesis/research?**  
A: Yes! Export the matrices and results for your analysis. The solver has been validated for accuracy. Please cite the software if used in publications.

**Q: Does it support plate/shell elements?**  
A: Not yet - currently only 3D beam/frame elements. Plates are on the roadmap.

**Q: Why is the Turkish Seismic Code included?**  
A: The developer is based in Turkey, and TBDY 2018 integration makes it valuable for Turkish students and engineers learning seismic design. The implementation has been validated against TBDY 2018 examples.

**Q: Can I run this on Mac/Linux?**  
A: Currently Windows-only via installer. If you run from source (Python), it *should* work on Mac/Linux but is untested.

**Q: How can I verify the accuracy myself?**  
A: Use the Matrix Spy tool to export stiffness matrices and compare with hand calculations or other software. The transparent nature of Open//Structures allows full verification of all calculations.

---

**⭐ If Open//Structures helped you learn FEM, please star this repo!**

[Download Now](https://github.com/Open//Structures-Project/Open//Structures/releases/latest) | [Report Bug](https://github.com/Open//Structures-Project/Open//Structures/issues) | [Website](https://Open//Structures-project.github.io/)

---

## 📄 Citation

If you use Open//Structures in academic work, please cite:

```
Azad, S. A. (2025). Open//Structures: A Transparent 3D Structural Analysis Engine 
for Learning Finite Element Methods (Version 0.655) [Computer software]. 
https://github.com/Open//Structures-Project/Open//Structures
```
