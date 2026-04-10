from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    """
    The blueprint for all strategies (Standard, Accumulator, etc).
    """

    @abstractmethod
    def decide_action(self, config, symbol, analysis_data, current_position):
        """
        Determines the action (BUY, SELL, HOLD, DIP_BUY) based on analysis data.
        Returns: (action_type, reason, score)
        """
        pass