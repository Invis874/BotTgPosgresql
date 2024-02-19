from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.orm import relationship

from .database import Base


class Departments(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)

class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    id_departments = Column(Integer, ForeignKey(Departments.id))
    cipher = Column(String)

class Contingent(Base):
    __tablename__ = "contingent"

    id = Column(Integer, primary_key=True, index=True)
    id_groups = Column(Integer, ForeignKey(Group.id))
    number_of_students = Column(Integer)
    date = Column(Date)