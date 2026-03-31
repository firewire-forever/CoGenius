# Experimental Data for Anonymous Submission

## Overview
This dataset contains the experimental results for an anonymous submission on automated cyber range generation from security reports using large language models and infrastructure-as-code techniques.

## Dataset Description
This repository includes structured experiment outputs, test case indices, and analysis scripts used to reproduce the statistics reported in the manuscript.

### Directory Structure

```
DOI/
├── README.md                          # This file
├── data/
│   ├── experiment_results/            # Experimental results (7 experiments)
│   │   └── *_exresults.txt            # Structured experiment summaries
│   └── test_cases/                    # Test case descriptions
│       └── test_cases_index.csv       # Index of all test PDFs
├── code/
│   └── analyze_results.py             # Analysis and visualization script
└── experiment_data.json               # Full results in JSON format
```

### Data Files

| File | Description | Format |
|------|-------------|--------|
| `data/experiment_results/*.txt` | Individual experiment results with timing, deployment status, and scenario details | Plain text |
| `experiment_data.json` | Complete dataset in structured JSON format | JSON |
| `code/analyze_results.py` | Python script to reproduce statistics and generate visualizations | Python |

## Experiment Results Summary

| Metric | Value |
|--------|-------|
| Total Experiments | 7 |
| Successful Deployments | 5 (71.4%) |
| Partial Success (Terraform only) | 2 (28.6%) |
| Avg. End-to-End Latency | ~1409 seconds (~23.5 minutes) |
| Avg. IAC Build Time | ~315 seconds (~5.3 minutes) |
| Total Networks Generated | 15 |
| Total Nodes Generated | 17 |
| Total Vulnerabilities | 25 |

### Time Breakdown by Stage

| Stage | Average Time (seconds) |
|-------|------------------------|
| PDF Extraction | 0.00* |
| VSDL Generation | 314.89 |
| VSDL Compilation | 0.17 |
| Terraform Deployment | 39.48 |
| Ansible Configuration | 475.51 |

*PDF extraction time recorded as 0 due to external service integration.

### Test Cases by Year

| Year | Count |
|------|-------|
| 2020 | 1 |
| 2021 | 3 |
| 2022 | 1 |
| 2023 | 1 |
| 2024 | 1 |

## Experiment Result File Format

Each `*_exresults.txt` file contains:

```
================================================================================
实验结果摘要 (Experiment Results Summary)
================================================================================

PDF文件: [PDF filename]
任务ID: [Task ID]
记录时间: [Timestamp]

----------------------------------------
【部署状态】(Deployment Status)
----------------------------------------
彻底成功部署: ✅ 是 / ❌ 否

----------------------------------------
【时间指标】(Time Metrics)
----------------------------------------
端到端延迟: [X] 秒
IAC平均构建时间: [X] 秒

各阶段耗时明细:
  1. PDF提取: [X] 秒
  2. VSDL生成: [X] 秒
  3. VSDL编译: [X] 秒
  4. Terraform部署: [X] 秒
  5. Ansible配置: [X] 秒

----------------------------------------
【场景概览】(Scenario Overview)
----------------------------------------
场景名称: [name]
场景时长: [X] TTU
网络数量: [X]
节点数量: [X]
漏洞数量: [X]
```

## Reproducing the Analysis

### Requirements

```bash
pip install matplotlib numpy
```

### Running the Analysis

```bash
cd DOI
python code/analyze_results.py
```

This will generate:
- `experiment_statistics.png` - Visualization of experiment results
- `experiment_data.json` - Structured JSON output

### Output Files

1. **experiment_statistics.png**: Contains 4 subplots:
   - Distribution of end-to-end latency
   - Distribution of IAC build time
   - Average time by stage (bar chart)
   - Deployment success rate (pie chart)

2. **experiment_data.json**: Contains:
   - Summary statistics
   - Individual experiment details

## Key Findings

1. **High Success Rate**: 71.4% of experiments achieved complete deployment (both Terraform and Ansible).

2. **VSDL Generation Efficiency**: The LLM-based VSDL generation averages ~5 minutes, demonstrating the efficiency of automated scenario creation.

3. **Perfect Terraform Success Rate**: 100% of experiments successfully deployed infrastructure via Terraform.

4. **Reasonable End-to-End Latency**: The average ~23.5 minutes end-to-end latency is acceptable for cyber range deployment scenarios.

5. **Complex Scenario Generation**: The system generated scenarios with an average of 2.1 networks, 2.4 nodes, and 3.6 vulnerabilities per experiment.

## System Architecture

The CoGenius system consists of:

1. **PDF Extraction Module**: Converts security reports to structured attack scenarios
2. **VSDL Generation Module**: Uses LangChain + ReAct Agent to generate scenario definitions
3. **Python VSDL Compiler**: Parses and validates VSDL scripts
4. **Infrastructure Generator**: Produces Terraform and Ansible code
5. **Deployment Engine**: Executes deployment on OpenStack



## Citation

If you use this dataset, please cite:



## License

This dataset is licensed under the **Creative Commons Attribution 4.0 International (CC BY 4.0)** license.


---

**Note**: The actual test PDF files (security reports) are not included in this dataset due to copyright restrictions. The reports are publicly available from their original sources (security vendor blogs, CVE databases, etc.). See `test_cases_index.csv` for references.