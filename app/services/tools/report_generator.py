from datetime import datetime
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class ReportGenerator:
    """
    Service responsible for generating formatted reports from interview results.
    Follows Single Responsibility Principle: Handles only formatting logic.
    """
    
    @staticmethod
    def generate_txt_report(results: List[Dict[str, Any]], source_filename: str) -> str:
        """
        Generate a human-readable text report from interview results.
        
        Args:
            results: List of result dictionaries containing 'skill' and 'questions'.
            source_filename: Name of the original resume file.
            
        Returns:
            Formatted string content of the report.
        """
        lines = []
        lines.append("AI INTERVIEW PREPARATION RESULTS")
        lines.append("==================================================")
        lines.append(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Source File:  {source_filename}.pdf") 
        lines.append("==================================================")
        lines.append("")
        lines.append("")
        
        for item in results:
            skill = item.get("skill", "Unknown Skill")
            questions = item.get("questions", [])
            
            lines.append(f"SKILL: {skill}")
            lines.append("-" * (len(skill) + 7))
            
            if not questions:
                lines.append("No questions generated.")
            else:
                for idx, question in enumerate(questions, 1):
                    lines.append(f"{idx}. {question}")
            
            lines.append("")
            lines.append("==================================================")
            lines.append("")
            
        return "\n".join(lines)
