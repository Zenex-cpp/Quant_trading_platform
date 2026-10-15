from decimal import Decimal
import pytest
from trading_platform.portfolio.allocation import (PortfolioConstraints, AllocationInput, allocate_equal_weight, allocate_inverse_vol, turnover, enforce_turnover, apply_hard_constraints)
from trading_platform.portfolio.capacity import estimate_capacity, assert_capacity, utilization
from trading_platform.portfolio.turnover import TurnoverPolicy, should_rebalance
from trading_platform.risk.budget import RiskBudgetLedger, RiskReservationBook, RiskReservation, BudgetScope

def D(x): return Decimal(str(x))

def test_equal_weight():
    w=allocate_equal_weight(['a','b','c'])
    assert sum(w.values(),D(0))==D('1')
    assert w['a']==w['b']
    assert w['a']>0
    assert w['c']>0

def test_inverse_vol_prefers_lower_vol():
    w=allocate_inverse_vol({'a':AllocationInput(D(0),D(1),D(0.1),D(1),D(1),D(0),D(1)), 'b':AllocationInput(D(0),D(1),D(0.2),D(1),D(1),D(0),D(1))})
    assert w['a'] > w['b']
    assert abs(sum(w.values(),D(0))-D(1)) < D('1e-20')

def test_constraints_hard_block():
    c=PortfolioConstraints(D(2),D(2),D(2),D('0.6'),D('0.8'),D('1'),D('0.01'))
    with pytest.raises(ValueError, match='CONCENTRATION_CONSTRAINT'):
        apply_hard_constraints({'a':D('0.7'),'b':D('0.3')},c,D('1'),D('0.4'),D('0.5'))

def test_turnover_budget():
    with pytest.raises(ValueError, match='TURNOVER_BUDGET_EXCEEDED'):
        enforce_turnover({'a':D('0.5'),'b':D('0.5')},{'a':D('0.9'),'b':D('0.1')},D('0.5'),D('0'))

def test_capacity():
    r=estimate_capacity(D('1000000'),D('0.1'),D('20'),D('400'))
    assert r.capacity_notional==D('50000')
    assert_capacity(D('40000'),r.capacity_notional)
    with pytest.raises(ValueError, match='CAPACITY_BREACH'):
        assert_capacity(D('60000'),r.capacity_notional)
    assert utilization(D('25000'),r.capacity_notional)==D('0.5')

def test_turnover_policy():
    p=TurnoverPolicy(D('0.5'),D('0.01'),D('10'),'1D')
    assert should_rebalance({'a':D('0.5')},{'a':D('0.6')},D('5'),p)
    assert not should_rebalance({'a':D('0.5')},{'a':D('0.505')},D('5'),p)
    assert not should_rebalance({'a':D('0.5')},{'a':D('0.6')},D('12'),p)

def test_reservation_release_cannot_reuse():
    l=RiskBudgetLedger(D('10'))
    b=RiskReservationBook()
    r=RiskReservation('r1',BudgetScope.ORDER,D('2'),D('2'))
    b.reserve(r,l); b.release('r1',l)
    with pytest.raises(ValueError, match='RELEASED_RESERVATION_REUSE'):
        b.consume('r1',l)

def test_reservation_double_consume():
    l=RiskBudgetLedger(D('10')); b=RiskReservationBook()
    r=RiskReservation('r1',BudgetScope.ORDER,D('2'),D('2'))
    b.reserve(r,l); b.consume('r1',l)
    with pytest.raises(ValueError, match='RESERVATION_DOUBLE_CONSUMPTION'):
        b.consume('r1',l)

def test_zero_risk_budget_cannot_reserve_positive():
    l=RiskBudgetLedger(D('0')); b=RiskReservationBook()
    with pytest.raises(ValueError, match='RISK_BUDGET_EXCEEDED'):
        b.reserve(RiskReservation('r',BudgetScope.ORDER,D('1'),D('1')),l)

def test_turnover_function():
    assert turnover({'a':D('0.5')},{'a':D('0.7')})==D('0.2')
